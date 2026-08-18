use criterion::{criterion_group, criterion_main, Criterion};
use fxradar_serve::{selftest, Bundle, Engine};

fn bench_scoring(c: &mut Criterion) {
    let dir = std::env::var("FXRADAR_BUNDLE").unwrap_or_else(|_| "../../models/bundle_v1.4.0".to_string());
    let bundle = Bundle::load(&dir).expect("bundle");
    let mut engine = Engine::new(bundle).expect("engine");
    let goldens = selftest::read_goldens(&engine).expect("goldens");
    let g = &goldens[0];
    c.bench_function("score_single_row_full_path", |b| {
        b.iter(|| engine.score(&g.windows, &g.pair).expect("score"))
    });
    let mut group = c.benchmark_group("throughput");
    group.sample_size(10);
    group.bench_function("score_10k_rows", |b| {
        b.iter(|| {
            for i in 0..10_000usize {
                let g = &goldens[i % goldens.len()];
                engine.score(&g.windows, &g.pair).expect("score");
            }
        })
    });
    group.finish();
}

criterion_group!(benches, bench_scoring);
criterion_main!(benches);
