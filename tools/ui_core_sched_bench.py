#!/usr/bin/env python3
# Synthetic scheduler check for the UI core pin: a FIFO-50 "UI" frame task vs a FIFO-51 burst load on core 5.
# Run on a PARKED comma: ssh comma 'test "$(cat /data/params/d/IsOnroad)" = 0 && sudo python3 - 10' < tools/ui_core_sched_bench.py
# 2026-10-07: UI on core 5 p99 13.7-14.0 ms, UI on core 6 p99 6.00 ms (nominal 6 ms). Proxy only, not the real renderer.

def burn(sec):
  end = time.perf_counter() + sec
  while time.perf_counter() < end: pass

def load(core, prio, busy, period, stop):
  os.sched_setaffinity(0, {core}); os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(prio))
  while not stop.is_set():
    t = time.perf_counter(); burn(busy)
    r = period - (time.perf_counter() - t)
    if r > 0: time.sleep(r)

def frames(core, prio, work, period, dur, out):
  os.sched_setaffinity(0, {core}); os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(prio))
  lat, late = [], []
  nxt = time.perf_counter(); end = nxt + dur
  while nxt < end:
    d = nxt - time.perf_counter()
    if d > 0: time.sleep(d)
    s = time.perf_counter(); burn(work); e = time.perf_counter()
    lat.append((e - s) * 1000); late.append((e - nxt) * 1000)
    nxt += period
  out.put((lat, late))

def run(core, loadcores, dur):
  stop = mp.Event(); out = mp.Queue()
  ps = [mp.Process(target=load, args=(c, 51, 0.008, 0.020, stop)) for c in loadcores]
  for p in ps: p.start()
  time.sleep(0.5)
  f = mp.Process(target=frames, args=(core, 50, 0.006, 0.020, dur, out)); f.start()
  lat, late = out.get(); f.join(); stop.set()
  for p in ps: p.join()
  q = lambda a, p: sorted(a)[min(len(a) - 1, int(len(a) * p))]
  return dict(n=len(lat), lat_p50=q(lat, .5), lat_p99=q(lat, .99), lat_max=max(lat), late_p99=q(late, .99), over20=sum(x > 20 for x in lat) / len(lat) * 100)

if __name__ == "__main__":
  dur = float(sys.argv[1])
  for rep in range(3):
    for name, core, lc in (("noload core6", 6, []), ("OLD ui@5 + FIFO51 load@5", 5, [5]), ("NEW ui@6 + FIFO51 load@5", 6, [5])):
      r = run(core, lc, dur)
      print(f"rep{rep} {name:28s} n={r['n']} p50={r['lat_p50']:.2f}ms p99={r['lat_p99']:.2f}ms max={r['lat_max']:.2f}ms late_p99={r['late_p99']:.2f}ms frames>20ms={r['over20']:.1f}%", flush=True)
