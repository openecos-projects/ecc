#!/usr/bin/env python

import os
import sys

current_dir = os.path.split(os.path.abspath(__file__))[0]
root = current_dir.rsplit('/', 1)[0]
sys.path.append(root)

from benchmark import benchmark_metrics, benchmark_statis, run_benchmark


def test_benchmark_batch():
    benchmark_json = f"{root}/benchmark/ics55_benchmark.json"
    
    # run batch
    run_benchmark(benchmark_json=benchmark_json,
                  target_dir="/nfs/home/huangzengrong/benchmark",
                  batch_name="ics55_batch_0")
    
    benchmark_statis(benchmark_dir="/nfs/home/huangzengrong/benchmark/ics55_batch_0")
    benchmark_metrics(benchmark_json=benchmark_json,
                     target_dir="/nfs/home/huangzengrong/benchmark",
                     batch_name="ics55_batch_0")
    
def test_benchmark_single():
    benchmark_json = f"{root}/benchmark/ics55_benchmark.json"
    
    # run batch
    run_benchmark(benchmark_json=benchmark_json,
                  target_dir="/nfs/home/huangzengrong/benchmark",
                  batch_name="ics55_batch_0",
                  design="arm9")
    
def test_benchmark_tapout():
    benchmark_json = f"{root}/benchmark/ics55_tapeout.json"
    
    # run batch
    run_benchmark(benchmark_json=benchmark_json,
                  target_dir="/nfs/home/huangzengrong/benchmark",
                  batch_name="ics55_tapeout")
    
    benchmark_statis(benchmark_dir="/nfs/home/huangzengrong/benchmark/ics55_tapeout")
    benchmark_metrics(benchmark_json=benchmark_json,
                     target_dir="/nfs/home/huangzengrong/benchmark",
                     batch_name="ics55_tapeout")
    
    
if __name__ == "__main__":
    # test_benchmark_batch()
    
    # test_benchmark_single()
    
    test_benchmark_tapout()

    exit(0)
