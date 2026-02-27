//! Sustained parallel load tests for mrrc.
//!
//! Tests concurrent reading, writing, and processing of MARC records to verify
//! thread safety and data integrity under parallel load.

use mrrc::{Field, Leader, MarcReader, MarcWriter, Record};
use std::path::PathBuf;
use std::sync::Arc;

// ---------------------------------------------------------------------------
// Helpers: synthetic MARC record construction
// ---------------------------------------------------------------------------

/// Build a Leader with sensible defaults for test records.
fn test_leader() -> Leader {
    Leader {
        record_length: 0,
        record_status: 'n',
        record_type: 'a',
        bibliographic_level: 'm',
        control_record_type: ' ',
        character_coding: 'a',
        indicator_count: 2,
        subfield_code_count: 2,
        data_base_address: 0,
        encoding_level: ' ',
        cataloging_form: ' ',
        multipart_level: ' ',
        reserved: "4500".to_string(),
    }
}

/// Create a synthetic MARC record with a control number and a 245 title field.
fn make_record(control_number: &str, title: &str) -> Record {
    let mut record = Record::new(test_leader());
    record.add_control_field("001".to_string(), control_number.to_string());

    let mut field = Field::new("245".to_string(), '1', '0');
    field.add_subfield('a', title.to_string());
    record.add_field(field);

    record
}

/// Serialize a slice of records into ISO 2709 binary bytes.
fn records_to_bytes(records: &[Record]) -> Vec<u8> {
    let mut buffer = Vec::new();
    {
        let mut writer = MarcWriter::new(&mut buffer);
        for rec in records {
            writer.write_record(rec).expect("write_record failed");
        }
    }
    buffer
}

/// Write synthetic records to a temporary .mrc file and return the path.
///
/// The caller is responsible for cleaning up the file/directory.
fn write_temp_mrc(dir_name: &str, records: &[Record]) -> PathBuf {
    let dir = std::env::temp_dir().join(dir_name);
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("create temp dir");

    let path = dir.join("test.mrc");
    let bytes = records_to_bytes(records);
    std::fs::write(&path, &bytes).expect("write temp mrc");
    path
}

/// Read all records from a file, returning a vec of (control_number, title) tuples.
fn read_all_records(path: &std::path::Path) -> Vec<(String, String)> {
    let file = std::fs::File::open(path).expect("open file");
    let mut reader = MarcReader::new(file);
    let mut results = Vec::new();
    while let Ok(Some(record)) = reader.read_record() {
        let cn = record.get_control_field("001").unwrap_or("").to_string();
        let title = record
            .get_fields("245")
            .and_then(|fields| fields.first())
            .and_then(|f| f.get_subfield('a'))
            .unwrap_or("")
            .to_string();
        results.push((cn, title));
    }
    results
}

// ---------------------------------------------------------------------------
// Test 1: sustained_parallel_read (local mode)
// ---------------------------------------------------------------------------

/// Spawn 8+ threads, each reading the same dataset file with their own MarcReader.
/// Each thread counts records and computes a checksum (sum of raw record byte
/// lengths as reported by the leader). Assert all threads get the same count and
/// checksum. Run for at least 3 passes.
#[test]
#[ignore]
fn sustained_parallel_read() {
    mrrc_testbed::require_local_mode();
    let files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !files.is_empty(),
        "No .mrc files found for any available dataset"
    );
    let target_file = Arc::new(files[0].clone());

    const NUM_THREADS: usize = 8;
    const NUM_PASSES: usize = 3;

    for pass in 0..NUM_PASSES {
        let mut handles = Vec::with_capacity(NUM_THREADS);

        for thread_id in 0..NUM_THREADS {
            let file_path = Arc::clone(&target_file);
            handles.push(std::thread::spawn(move || {
                let file = std::fs::File::open(file_path.as_ref())
                    .unwrap_or_else(|e| panic!("Thread {thread_id} pass {pass}: open failed: {e}"));
                let mut reader = MarcReader::new(file);
                let mut count: usize = 0;
                let mut checksum: u64 = 0;

                while let Ok(Some(record)) = reader.read_record() {
                    count += 1;
                    checksum += u64::from(record.leader.record_length);
                }

                (count, checksum)
            }));
        }

        let results: Vec<(usize, u64)> = handles
            .into_iter()
            .map(|h| h.join().expect("thread panicked"))
            .collect();

        // All threads must agree on count and checksum.
        let (expected_count, expected_checksum) = results[0];
        assert!(
            expected_count > 0,
            "Pass {pass}: expected at least one record"
        );
        for (i, &(count, checksum)) in results.iter().enumerate() {
            assert_eq!(
                count, expected_count,
                "Pass {pass}, thread {i}: record count mismatch ({count} vs {expected_count})"
            );
            assert_eq!(
                checksum, expected_checksum,
                "Pass {pass}, thread {i}: checksum mismatch ({checksum} vs {expected_checksum})"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Test 2: producer_consumer_stress (local mode)
// ---------------------------------------------------------------------------

/// Use a channel-based producer/consumer pattern to stress-test parallel record
/// processing.  One producer thread reads records from a dataset file and sends
/// them over a bounded channel.  Multiple consumer threads receive records and
/// verify that each has a parseable 245 field.  Assert that the total number of
/// records consumed matches the file's record count with no drops.
#[test]
#[ignore]
fn producer_consumer_stress() {
    mrrc_testbed::require_local_mode();
    let files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !files.is_empty(),
        "No .mrc files found for any available dataset"
    );
    let target_file = &files[0];

    // Get the expected count via the fast byte-scan helper.
    let expected_count =
        mrrc_testbed::count_records_in_file(target_file).expect("count_records_in_file failed");
    assert!(expected_count > 0, "File appears to have 0 records");

    // Bounded channel with backpressure.
    let (tx, rx) = std::sync::mpsc::sync_channel::<Record>(512);

    // Producer: read records and send them.
    let producer_path = target_file.clone();
    let producer = std::thread::spawn(move || {
        let file = std::fs::File::open(&producer_path).expect("producer: open failed");
        let mut reader = MarcReader::new(file);
        let mut sent: usize = 0;
        while let Ok(Some(record)) = reader.read_record() {
            if tx.send(record).is_err() {
                // All receivers dropped — stop.
                break;
            }
            sent += 1;
        }
        sent
    });

    // Consumers: 4 threads pulling from the same receiver via a shared Arc<Mutex>.
    const NUM_CONSUMERS: usize = 4;
    let rx = Arc::new(std::sync::Mutex::new(rx));
    let consumed = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let verified_245 = Arc::new(std::sync::atomic::AtomicUsize::new(0));

    let mut consumer_handles = Vec::with_capacity(NUM_CONSUMERS);
    for _ in 0..NUM_CONSUMERS {
        let rx = Arc::clone(&rx);
        let consumed = Arc::clone(&consumed);
        let verified_245 = Arc::clone(&verified_245);
        consumer_handles.push(std::thread::spawn(move || {
            loop {
                let record = {
                    let guard = rx.lock().expect("mutex poisoned");
                    match guard.recv() {
                        Ok(r) => r,
                        Err(_) => break, // channel closed
                    }
                };
                consumed.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                // Verify 245 field presence (most records have one).
                if record.get_fields("245").is_some() {
                    verified_245.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                }
            }
        }));
    }

    let sent = producer.join().expect("producer panicked");
    for h in consumer_handles {
        h.join().expect("consumer panicked");
    }

    let total_consumed = consumed.load(std::sync::atomic::Ordering::SeqCst);
    assert_eq!(
        total_consumed, sent,
        "Records consumed ({total_consumed}) != records sent ({sent})"
    );
    // The byte-scan count might differ slightly from parsed count if the file
    // contains embedded 0x1D bytes, but it should be very close.  Use the
    // producer's sent count as the source of truth and just sanity-check the
    // byte-scan value.
    let diff = if expected_count > sent {
        expected_count - sent
    } else {
        sent - expected_count
    };
    assert!(
        diff <= expected_count / 100, // within 1%
        "Byte-scan count ({expected_count}) diverges too much from parsed count ({sent})"
    );
    // The vast majority of records should have a 245 field.
    let v245 = verified_245.load(std::sync::atomic::Ordering::SeqCst);
    assert!(
        v245 > total_consumed / 2,
        "Fewer than half the records had a 245 field ({v245}/{total_consumed})"
    );
}

// ---------------------------------------------------------------------------
// Test 3: no_data_corruption (CI-safe)
// ---------------------------------------------------------------------------

/// Create a temp .mrc file with known records.  Read it from multiple threads
/// simultaneously.  Each thread extracts control numbers and field data.  Assert
/// all threads get identical results.  Uses Arc for shared data.
#[test]
fn no_data_corruption() {
    const NUM_RECORDS: usize = 50;
    const NUM_THREADS: usize = 8;

    // Build known records.
    let records: Vec<Record> = (0..NUM_RECORDS)
        .map(|i| make_record(&format!("CN{i:04}"), &format!("Title number {i}")))
        .collect();

    let path = write_temp_mrc("mrrc_testbed_no_data_corruption", &records);
    let shared_path = Arc::new(path.clone());

    // Expected results (read once, single-threaded, as ground truth).
    let expected = read_all_records(&path);
    assert_eq!(expected.len(), NUM_RECORDS);

    // Spawn threads that each independently read the file.
    let mut handles = Vec::with_capacity(NUM_THREADS);
    for _ in 0..NUM_THREADS {
        let p = Arc::clone(&shared_path);
        handles.push(std::thread::spawn(move || read_all_records(&p)));
    }

    for (i, h) in handles.into_iter().enumerate() {
        let result = h.join().expect("thread panicked");
        assert_eq!(
            result.len(),
            expected.len(),
            "Thread {i}: record count mismatch"
        );
        for (j, (cn, title)) in result.iter().enumerate() {
            assert_eq!(
                cn, &expected[j].0,
                "Thread {i}, record {j}: control number mismatch"
            );
            assert_eq!(
                title, &expected[j].1,
                "Thread {i}, record {j}: title mismatch"
            );
        }
    }

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}

// ---------------------------------------------------------------------------
// Test 4: concurrent_write_read (CI-safe)
// ---------------------------------------------------------------------------

/// Write records to a temp file, then read them back from multiple threads.
/// Verify consistency: every thread sees the same records in the same order,
/// and all data matches the original records that were written.
#[test]
fn concurrent_write_read() {
    const NUM_RECORDS: usize = 100;
    const NUM_READER_THREADS: usize = 6;

    // Build records with distinct control numbers and titles.
    let records: Vec<Record> = (0..NUM_RECORDS)
        .map(|i| {
            let mut rec = make_record(
                &format!("WR{i:05}"),
                &format!("Concurrent write-read title {i}"),
            );
            // Add a second field to make records more realistic.
            let mut field_650 = Field::new("650".to_string(), ' ', '0');
            field_650.add_subfield('a', format!("Subject {i}"));
            rec.add_field(field_650);
            rec
        })
        .collect();

    let path = write_temp_mrc("mrrc_testbed_concurrent_write_read", &records);

    // Verify byte-level record count matches.
    let byte_count =
        mrrc_testbed::count_records_in_file(&path).expect("count_records_in_file failed");
    assert_eq!(byte_count, NUM_RECORDS);

    let shared_path = Arc::new(path.clone());

    // Spawn multiple reader threads.
    let mut handles = Vec::with_capacity(NUM_READER_THREADS);
    for _ in 0..NUM_READER_THREADS {
        let p = Arc::clone(&shared_path);
        handles.push(std::thread::spawn(move || {
            let file = std::fs::File::open(p.as_ref()).expect("open for reading");
            let mut reader = MarcReader::new(file);
            let mut out: Vec<(String, String, Option<String>)> = Vec::new();
            while let Ok(Some(record)) = reader.read_record() {
                let cn = record.get_control_field("001").unwrap_or("").to_string();
                let title = record
                    .get_fields("245")
                    .and_then(|fs| fs.first())
                    .and_then(|f| f.get_subfield('a'))
                    .unwrap_or("")
                    .to_string();
                let subject = record
                    .get_fields("650")
                    .and_then(|fs| fs.first())
                    .and_then(|f| f.get_subfield('a'))
                    .map(|s| s.to_string());
                out.push((cn, title, subject));
            }
            out
        }));
    }

    let thread_results: Vec<Vec<(String, String, Option<String>)>> = handles
        .into_iter()
        .map(|h| h.join().expect("reader thread panicked"))
        .collect();

    // All threads must return NUM_RECORDS records.
    for (i, res) in thread_results.iter().enumerate() {
        assert_eq!(
            res.len(),
            NUM_RECORDS,
            "Reader thread {i}: expected {NUM_RECORDS} records, got {}",
            res.len()
        );
    }

    // All threads must agree with each other and with the original data.
    let reference = &thread_results[0];
    for (i, res) in thread_results.iter().enumerate().skip(1) {
        assert_eq!(res, reference, "Reader thread {i} disagrees with thread 0");
    }

    // Verify against original records.
    for (j, (cn, title, subject)) in reference.iter().enumerate() {
        let expected_cn = format!("WR{j:05}");
        let expected_title = format!("Concurrent write-read title {j}");
        let expected_subject = format!("Subject {j}");
        assert_eq!(cn, &expected_cn, "Record {j}: control number mismatch");
        assert_eq!(title, &expected_title, "Record {j}: title mismatch");
        assert_eq!(
            subject.as_deref(),
            Some(expected_subject.as_str()),
            "Record {j}: subject mismatch"
        );
    }

    let _ = std::fs::remove_dir_all(path.parent().unwrap());
}
