#!/usr/bin/env python3
"""Profile all eight verified SAN-90 RBW steps and restore/reopen safely."""

from __future__ import annotations

import json
import resource
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from backend.analyzer.models import AnalyzerSettings
from backend.analyzer.san90 import San90Source
from backend.analyzer.tradeoff import SAN90_RESOLUTION_TRADEOFF_STEPS,match_actual_tradeoff_step,visible_rows


def rss_mib()->float:
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):return float(line.split()[1])/1024
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024


def safe_settings()->AnalyzerSettings:
    return AnalyzerSettings(mode='rta',center_frequency_hz=2.45e9,rbw_mode='auto',rbw_hz=None,
        reference_level_dbm=0.0,attenuation_db=None,preamplifier='off',gain_strategy='low-noise',
        window='blackman-nuttall',detector='positive-peak')


def run(duration_s:float=2.0)->list[dict[str,object]]:
    source=San90Source();safe=safe_settings();results=[]
    try:
        source.connect();source.apply_settings(safe);source.start()
        for expected in SAN90_RESOLUTION_TRADEOFF_STEPS:
            started=time.perf_counter();source.apply_settings(source.get_settings_state().requested.updated(rbw_mode='manual',rbw_hz=expected.requested_rbw_hz));reconfiguration_s=time.perf_counter()-started
            state=source.get_settings_state();actual=state.actual
            matched=match_actual_tradeoff_step(SAN90_RESOLUTION_TRADEOFF_STEPS,actual_rbw_hz=actual.rbw_hz,point_count=actual.point_count,fft_size=actual.fft_size,actual_span_hz=actual.span_hz)
            if matched is None or matched.index!=expected.index:raise AssertionError(f'profile mismatch for index {expected.index}: {actual}')
            before_frames=source.get_status().sdk_frames_received;before_cpu=time.process_time();before_rss=rss_mib()
            temporal_count=temporal_traces=waterfall_batches=waterfall_rows=spectrum_bytes=waterfall_bytes=0
            deadline=time.monotonic()+duration_s
            while time.monotonic()<deadline:
                temporal=source.read_spectrum_temporal()
                if temporal is not None:
                    if temporal.generation!=state.configuration_generation:raise AssertionError('stale temporal generation')
                    temporal_count+=1;temporal_traces+=temporal.traces_integrated;spectrum_bytes+=128+temporal.point_count*8
                batch=source.read_waterfall_batch()
                if batch is not None:
                    if batch.configuration_generation!=state.configuration_generation:raise AssertionError('stale waterfall generation')
                    waterfall_batches+=1;waterfall_rows+=batch.row_count;waterfall_bytes+=120+batch.values.size
                time.sleep(.0005)
            elapsed=duration_s;native_traces=source.get_status().sdk_frames_received-before_frames
            wf=source.get_waterfall_metrics();temporal_metrics=source.get_spectrum_temporal_metrics()
            result={
                'index':expected.index,'requested_rbw_hz':expected.requested_rbw_hz,'actual_rbw_hz':actual.rbw_hz,
                'point_count':actual.point_count,'fft_size':actual.fft_size,'sdk_traces_per_second':native_traces/elapsed,
                'effective_point_rate':native_traces*actual.point_count/elapsed,'spectrum_temporal_fps':temporal_count/elapsed,
                'mean_traces_per_spectrum_frame':temporal_traces/temporal_count if temporal_count else 0,
                'waterfall_rows_per_second':waterfall_rows/elapsed,'waterfall_batches_per_second':waterfall_batches/elapsed,
                'rows_per_batch':expected.waterfall_rows_per_batch,
                'mean_traces_per_waterfall_row':None if wf is None else wf.mean_traces_per_row,
                'spectrum_wire_bytes_per_second':spectrum_bytes/elapsed,'waterfall_wire_bytes_per_second':waterfall_bytes/elapsed,
                'process_cpu_percent':100*(time.process_time()-before_cpu)/elapsed,'rss_before_mib':before_rss,'rss_after_mib':rss_mib(),
                'reconfiguration_latency_ms':reconfiguration_s*1000,'visible_time_span_seconds':5.0,
                'visible_rows':visible_rows(expected.waterfall_rows_per_second),'configuration_generation':state.configuration_generation,
                'spectrum_temporal_metrics':temporal_metrics,
            }
            results.append(result);print(json.dumps(result,sort_keys=True),flush=True)
        source.apply_settings(safe)
        restored=source.get_settings_state();print(json.dumps({'restored':asdict(restored)},sort_keys=True),flush=True)
    finally:
        source.stop();source.disconnect()
    reopened=San90Source()
    try:
        reopened.connect();reopened.apply_settings(safe);reopened.start();time.sleep(.1)
        print(json.dumps({'immediate_reopen':asdict(reopened.get_settings_state())},sort_keys=True),flush=True)
    finally:
        reopened.stop();reopened.disconnect()
    return results


if __name__=='__main__':run()
