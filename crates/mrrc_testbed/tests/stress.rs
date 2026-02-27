//! Stress tests: memory stability, throughput, thread scaling, and resource cleanup.
//!
//! Tests marked `#[ignore]` require `MRRC_TEST_MODE=local` and downloaded datasets.
//! The `resource_cleanup` test runs in CI mode using synthetic MARC data.

use std::alloc::{GlobalAlloc, Layout, System};
use std::fs::{self, File};
use std::io::Cursor;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use mrrc::{MarcReader, RecoveryMode};

// ---------------------------------------------------------------------------
// Counting allocator — tracks current and peak allocated bytes so we can
// detect unbounded memory growth without platform-specific APIs.
// ---------------------------------------------------------------------------

struct CountingAllocator {
    inner: System,
    current: AtomicUsize,
    peak: AtomicUsize,
}

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let ptr = unsafe { self.inner.alloc(layout) };
        if !ptr.is_null() {
            let prev = self.current.fetch_add(layout.size(), Ordering::Relaxed);
            let new = prev + layout.size();
            // Update peak using a compare-and-swap loop.
            let mut peak = self.peak.load(Ordering::Relaxed);
            while new > peak {
                match self.peak.compare_exchange_weak(
                    peak,
                    new,
                    Ordering::Relaxed,
                    Ordering::Relaxed,
                ) {
                    Ok(_) => break,
                    Err(actual) => peak = actual,
                }
            }
        }
        ptr
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { self.inner.dealloc(ptr, layout) };
        self.current.fetch_sub(layout.size(), Ordering::Relaxed);
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator {
    inner: System,
    current: AtomicUsize::new(0),
    peak: AtomicUsize::new(0),
};

impl CountingAllocator {
    /// Return the current number of bytes allocated.
    fn current_bytes(&self) -> usize {
        self.current.load(Ordering::Relaxed)
    }

    /// Return (and reset) the peak allocation counter.
    fn take_peak(&self) -> usize {
        self.peak.swap(self.current_bytes(), Ordering::Relaxed)
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Read every record from a `.mrc` file using `MarcReader` in lenient mode
/// and return the count of successfully parsed records.
fn read_all_records(path: &Path) -> usize {
    let file = File::open(path).expect("failed to open .mrc file");
    let mut reader = MarcReader::new(file).with_recovery_mode(RecoveryMode::Lenient);
    let mut count = 0usize;
    loop {
        match reader.read_record() {
            Ok(Some(_)) => count += 1,
            Ok(None) => break,
            Err(_) => break, // stop on hard errors
        }
    }
    count
}

/// Build a minimal valid MARC binary record in memory.
///
/// This is used by the `resource_cleanup` test so it can run without any
/// external fixture files.
fn build_synthetic_marc_bytes(n_records: usize) -> Vec<u8> {
    const FIELD_TERMINATOR: u8 = 0x1E;
    const SUBFIELD_DELIMITER: u8 = 0x1F;
    const RECORD_TERMINATOR: u8 = 0x1D;

    let mut all = Vec::new();

    for i in 0..n_records {
        // Data field 245 with a title
        let title = format!("Record {i}");
        let mut field_245 = Vec::new();
        field_245.extend_from_slice(b"10"); // indicators
        field_245.push(SUBFIELD_DELIMITER);
        field_245.push(b'a');
        field_245.extend_from_slice(title.as_bytes());
        field_245.push(FIELD_TERMINATOR);

        // Directory: one entry (tag 3 + length 4 + start 5 = 12 bytes) + terminator
        let mut directory = Vec::new();
        directory.extend_from_slice(b"245");
        directory.extend_from_slice(format!("{:04}", field_245.len()).as_bytes());
        directory.extend_from_slice(b"00000");

        let base_address = 24 + directory.len() + 1; // +1 for directory terminator
        directory.push(FIELD_TERMINATOR);

        let record_length = base_address + field_245.len() + 1; // +1 for record terminator

        // Leader (24 bytes)
        let mut leader = Vec::new();
        leader.extend_from_slice(format!("{record_length:05}").as_bytes()); // 0-4
        leader.push(b'n'); // 5: status
        leader.push(b'a'); // 6: type
        leader.push(b'm'); // 7: bib level
        leader.push(b' '); // 8: control type
        leader.push(b'a'); // 9: character coding
        leader.push(b'2'); // 10: indicator count
        leader.push(b'2'); // 11: subfield code count
        leader.extend_from_slice(format!("{base_address:05}").as_bytes()); // 12-16
        leader.push(b' '); // 17: encoding level
        leader.push(b' '); // 18: cataloging form
        leader.push(b' '); // 19: multipart level
        leader.extend_from_slice(b"4500"); // 20-23: entry map

        all.extend_from_slice(&leader);
        all.extend_from_slice(&directory);
        all.extend_from_slice(&field_245);
        all.push(RECORD_TERMINATOR);
    }

    all
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

/// Read a large dataset multiple times and verify that peak memory stays stable.
///
/// Requires local mode + the "watson" dataset.
#[test]
#[ignore]
fn memory_stability() {
    mrrc_testbed::require_local_mode();
    let files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !files.is_empty(),
        "No .mrc files found for any available dataset"
    );

    const PASSES: usize = 4;
    let mut peak_per_pass: Vec<usize> = Vec::with_capacity(PASSES);

    for pass in 0..PASSES {
        // Reset peak before the pass.
        ALLOCATOR.take_peak();

        let mut total_records = 0usize;
        for file in &files {
            total_records += read_all_records(file);
        }

        let peak = ALLOCATOR.take_peak();
        eprintln!(
            "pass {pass}: {total_records} records, peak alloc = {} MiB",
            peak / (1024 * 1024)
        );
        peak_per_pass.push(peak);
    }

    // Skip pass 0 (startup overhead inflates the first-pass peak).
    // Compare passes 1+ against pass 1 as baseline.
    let baseline = peak_per_pass[1] as f64;
    for (i, &peak) in peak_per_pass.iter().enumerate().skip(2) {
        let ratio = peak as f64 / baseline;
        assert!(
            (0.5..=1.5).contains(&ratio),
            "pass {i} peak ({peak}) deviated {:.0}% from baseline ({baseline}); ratio = {ratio:.3}",
            (ratio - 1.0).abs() * 100.0
        );
    }
}

/// Measure sustained throughput (records/sec) across multiple passes.
///
/// Asserts throughput does not degrade by more than 20% from the first pass to the last.
#[test]
#[ignore]
fn throughput_sustained() {
    mrrc_testbed::require_local_mode();
    let files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !files.is_empty(),
        "No .mrc files found for any available dataset"
    );

    const PASSES: usize = 5;
    let mut throughputs: Vec<f64> = Vec::with_capacity(PASSES);

    for pass in 0..PASSES {
        let start = Instant::now();
        let mut total_records = 0usize;
        for file in &files {
            total_records += read_all_records(file);
        }
        let elapsed = start.elapsed().as_secs_f64();
        let rps = total_records as f64 / elapsed;
        eprintln!("pass {pass}: {total_records} records in {elapsed:.2}s = {rps:.0} rec/s");
        throughputs.push(rps);
    }

    let first = throughputs[0];
    let last = *throughputs.last().unwrap();
    let ratio = last / first;
    assert!(
        ratio >= 0.8,
        "throughput degraded from {first:.0} to {last:.0} rec/s ({:.0}% of first pass); \
         expected at least 80%",
        ratio * 100.0,
    );
}

/// Measure total throughput with 1, 2, 4, and 8 threads reading the same dataset.
///
/// Asserts at least 1.5x scaling from 1 thread to 4 threads.
#[test]
#[ignore]
fn thread_scaling() {
    mrrc_testbed::require_local_mode();
    let files = mrrc_testbed::collect_dataset_files(mrrc_testbed::DATASET_NAMES);
    assert!(
        !files.is_empty(),
        "No .mrc files found for any available dataset"
    );

    let files = Arc::new(files);

    let thread_counts = [1, 2, 4, 8];
    let mut throughputs: Vec<(usize, f64)> = Vec::new();

    for &n_threads in &thread_counts {
        let start = Instant::now();
        let total_records = Arc::new(AtomicUsize::new(0));

        let mut handles = Vec::with_capacity(n_threads);
        for _ in 0..n_threads {
            let files = Arc::clone(&files);
            let counter = Arc::clone(&total_records);
            handles.push(std::thread::spawn(move || {
                let mut local_count = 0usize;
                for file in files.iter() {
                    local_count += read_all_records(file);
                }
                counter.fetch_add(local_count, Ordering::Relaxed);
            }));
        }

        for h in handles {
            h.join().expect("thread panicked");
        }

        let elapsed = start.elapsed().as_secs_f64();
        let records = total_records.load(Ordering::Relaxed);
        let rps = records as f64 / elapsed;
        eprintln!("{n_threads} thread(s): {records} records in {elapsed:.2}s = {rps:.0} rec/s");
        throughputs.push((n_threads, rps));
    }

    // Find the 1-thread and 4-thread throughputs.
    let tp1 = throughputs
        .iter()
        .find(|(n, _)| *n == 1)
        .map(|(_, t)| *t)
        .expect("missing 1-thread result");
    let tp4 = throughputs
        .iter()
        .find(|(n, _)| *n == 4)
        .map(|(_, t)| *t)
        .expect("missing 4-thread result");

    let scaling = tp4 / tp1;
    assert!(
        scaling >= 1.5,
        "4-thread throughput ({tp4:.0}) is only {scaling:.2}x of 1-thread ({tp1:.0}); \
         expected >= 1.5x"
    );
}

/// Open and close a `MarcReader` many times on the same data to verify that
/// file handles and memory are released properly.
///
/// This test runs in CI mode using synthetic MARC data written to a temporary
/// file. If `get_dataset("default")` succeeds, that file is used instead.
#[test]
fn resource_cleanup() {
    const ITERATIONS: usize = 200;

    // Try to use a real dataset; fall back to a synthetic temp file.
    let (path, _tmpdir) = match mrrc_testbed::get_dataset("default") {
        Ok(p) => (p, None),
        Err(_) => {
            // Build a temporary .mrc file with 50 synthetic records.
            let dir = std::env::temp_dir().join("mrrc_testbed_stress_cleanup");
            let _ = fs::remove_dir_all(&dir);
            fs::create_dir_all(&dir).expect("create temp dir");
            let file_path = dir.join("synthetic.mrc");
            let bytes = build_synthetic_marc_bytes(50);
            fs::write(&file_path, &bytes).expect("write synthetic .mrc");
            (file_path, Some(dir))
        }
    };

    // Record memory before the loop.
    let mem_before = ALLOCATOR.current_bytes();

    for i in 0..ITERATIONS {
        // --- File-based reader ---
        let count_file = read_all_records(&path);
        assert!(
            count_file > 0,
            "iteration {i}: expected at least one record from file"
        );

        // --- In-memory reader (exercises the same parsing path) ---
        let data = fs::read(&path).expect("read file for in-memory test");
        let cursor = Cursor::new(data);
        let mut reader = MarcReader::new(cursor).with_recovery_mode(RecoveryMode::Lenient);
        let mut count_mem = 0usize;
        loop {
            match reader.read_record() {
                Ok(Some(_)) => count_mem += 1,
                Ok(None) => break,
                Err(_) => break,
            }
        }
        assert_eq!(
            count_file, count_mem,
            "iteration {i}: file and memory reader counts differ"
        );
    }

    let mem_after = ALLOCATOR.current_bytes();

    // Allow up to 2 MiB of drift — anything larger suggests a systematic leak.
    let drift = mem_after.saturating_sub(mem_before);
    let max_drift = 2 * 1024 * 1024;
    assert!(
        drift <= max_drift,
        "memory grew by {} bytes ({:.1} MiB) over {ITERATIONS} iterations; \
         max allowed = {max_drift} bytes",
        drift,
        drift as f64 / (1024.0 * 1024.0),
    );

    // Clean up temp dir if we created one.
    if let Some(dir) = _tmpdir {
        let _ = fs::remove_dir_all(&dir);
    }
}
