<script lang="ts">
  // Phase 0 spike: prove BLE on the tablet. Connect an FTMS trainer and a Zwift Ride,
  // hold an ERG target, react to controller buttons, and count disconnects over a long session.
  import { onMount } from "svelte";
  import * as dev from "./lib/devices";
  import Logo from "./lib/Logo.svelte";
  import { getVersion } from "@tauri-apps/api/app";
  import type { Button, Found, BikeData } from "./lib/devices";

  type Link = { name: string; connected: boolean; since: number | null; drops: number; denied: boolean };
  const emptyLink = (): Link => ({ name: "", connected: false, since: null, drops: 0, denied: false });

  let found = $state<Found[]>([]);
  let scanning = $state(false);
  let busy = $state<string | null>(null);
  let error = $state<string | null>(null);

  let trainer = $state<Link>(emptyLink());
  let controller = $state<Link>(emptyLink());
  let data = $state<BikeData>({ speedKmh: null, cadenceRpm: null, powerW: null, hrBpm: null });

  let target = $state(150);
  let erg = $state(true);
  let presses = $state<{ at: string; button: Button }[]>([]);
  let raw = $state<dev.RawControllerMessage | null>(null);
  // distinct Zwift Ride bitmaps, newest first (bit cleared = pressed): to identify unmapped buttons
  let bitmaps = $state<{ at: string; bitmap: string }[]>([]);
  // trainer diagnostics: target replies, control point answers, machine status
  let battery = $state<number | null>(null);
  let trainerLog = $state<{ at: string; text: string }[]>([]);
  const logTrainer = (text: string) =>
    (trainerLog = [{ at: new Date().toLocaleTimeString(), text }, ...trainerLog].slice(0, 14));
  let now = $state(Date.now());

  const fmt = (ms: number) => {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h ? h + ":" : ""}${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  };

  async function run<T>(label: string, f: () => Promise<T>): Promise<T | undefined> {
    busy = label;
    error = null;
    try {
      return await f();
    } catch (e) {
      error = `${label}: ${e}`;
    } finally {
      busy = null;
    }
  }

  async function doScan() {
    scanning = true;
    found = (await run("Scan", () => dev.scan(6))) ?? found;
    scanning = false;
  }

  async function connect(d: Found) {
    if (d.kind === "trainer") {
      const denied = await run("Trainer", () => dev.connectTrainer(d));
      if (denied !== undefined && erg) await applyTarget();
    } else if (d.kind === "controller") {
      await run("Controller", () => dev.connectController(d));
    }
  }

  async function applyTarget() {
    if (!trainer.connected) return;
    const label = erg ? `ERG ${target} W` : "Free ride";
    const reply = await run("ERG", () => (erg ? dev.setPower(target) : dev.freeRide()));
    if (reply !== undefined) logTrainer(`${label} → ${dev.replyText(reply)}`);
  }

  function changeTarget(delta: number) {
    target = Math.min(1000, Math.max(50, target + delta));
    if (erg) applyTarget();
  }

  function toggleErg() {
    erg = !erg;
    applyTarget();
  }

  function handleButton(b: Button) {
    presses = [{ at: new Date().toLocaleTimeString(), button: b }, ...presses].slice(0, 12);
    if (b === "up" || b === "shiftUp") changeTarget(10);
    else if (b === "down" || b === "shiftDown") changeTarget(-10);
    else if (b === "a") toggleErg();
  }

  let version = $state("");

  onMount(() => {
    getVersion().then((v) => (version = v));
    const tick = setInterval(() => (now = Date.now()), 1000);
    const unlisten = [
      dev.onTrainerData((d) => (data = d)),
      dev.onButton(handleButton),
      dev.onRaw((m) => {
        raw = m;
        if (m.bitmap && m.bitmap !== bitmaps[0]?.bitmap)
          bitmaps = [{ at: new Date().toLocaleTimeString(), bitmap: m.bitmap }, ...bitmaps].slice(0, 6);
      }),
      dev.onBattery((p) => (battery = p)),
      dev.onControlReply((op, reply) => logTrainer(`control ${op} answered ${dev.replyText(reply)}`)),
      dev.onMachineStatus((text) => logTrainer(`trainer: ${text}`)),
      dev.onStatus((s) => {
        const link = s.kind === "trainer" ? trainer : s.kind === "controller" ? controller : null;
        if (!link) return;
        if (link.connected && !s.connected) link.drops += 1;
        // uptime of the current connection: restarts on every (re)connect
        link.since = s.connected ? (link.connected ? link.since : Date.now()) : null;
        link.connected = s.connected;
        link.name = s.name;
        link.denied = s.denied;
      }),
    ];
    return () => {
      clearInterval(tick);
      unlisten.forEach((p) => p.then((f) => f()));
    };
  });

  const value = (v: number | null, digits = 0) => (v == null ? "—" : v.toFixed(digits));
</script>

<main>
  <header>
    <h1><Logo size={36} /> BikeTo <small>BLE spike {version && `v${version}`}</small></h1>
    <div class="actions">
      <button class="primary" onclick={doScan} disabled={scanning}>{scanning ? "Scanning…" : "Scan"}</button>
      <button onclick={() => run("Disconnect", dev.disconnectAll)}>Disconnect all</button>
    </div>
  </header>

  {#if error}<p class="error">{error}</p>{/if}

  {#if found.length}
    <section class="card">
      <h2>Devices</h2>
      <ul class="found">
        {#each found as d (d.address)}
          <li>
            <span class="kind">{d.kind}</span>
            <span class="name">{d.name}</span>
            <span class="muted">{d.rssi ?? ""} dBm</span>
            {#if d.kind !== "heartRate"}
              <button onclick={() => connect(d)} disabled={busy !== null}>Connect</button>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <div class="grid">
    <section class="card">
      <h2>Trainer <span class="dot" class:on={trainer.connected}></span></h2>
      <p class="muted">{trainer.name || "not connected"}{trainer.denied ? " · control refused, trying anyway" : ""}</p>
      <div class="metrics">
        <div><b>{value(data.powerW)}</b><span>W</span></div>
        <div><b>{value(data.cadenceRpm)}</b><span>rpm</span></div>
        <div><b>{value(data.speedKmh, 1)}</b><span>km/h</span></div>
        <div><b>{value(data.hrBpm)}</b><span>bpm</span></div>
      </div>
      <div class="erg">
        <button onclick={() => changeTarget(-10)} disabled={!erg}>−10</button>
        <div class="target"><b>{erg ? target : "Free"}</b><span>{erg ? "W target" : "flat road"}</span></div>
        <button onclick={() => changeTarget(10)} disabled={!erg}>+10</button>
        <button onclick={toggleErg}>{erg ? "Free ride" : "ERG"}</button>
      </div>
    </section>

    <section class="card">
      <h2>
        Controller <span class="dot" class:on={controller.connected}></span>
        {#if battery !== null}<span class="battery" class:low={battery <= 20}>🔋 {battery}%</span>{/if}
      </h2>
      <p class="muted">{controller.name || "not connected"} · up/down ±10 W · A toggles ERG</p>
      <ol class="presses">
        {#each presses as p, i (p.at + p.button + i)}
          <li><span class="muted">{p.at}</span> {p.button}</li>
        {:else}
          <li class="muted">Press a button…</li>
        {/each}
      </ol>
      <p class="raw muted">{raw?.hex ?? " "}</p>
      {#if bitmaps.length}
        <p class="muted small">Ride bitmap changes (bit cleared = pressed):</p>
        <ul class="raw">
          {#each bitmaps as b, i (b.at + b.bitmap + i)}
            <li><span class="muted">{b.at}</span> {b.bitmap}</li>
          {/each}
        </ul>
      {/if}
    </section>

    <section class="card">
      <h2>Session</h2>
      <dl>
        <dt>Trainer up</dt><dd>{trainer.since ? fmt(now - trainer.since) : "—"}</dd>
        <dt>Trainer drops</dt><dd class:bad={trainer.drops > 0}>{trainer.drops}</dd>
        <dt>Controller up</dt><dd>{controller.since ? fmt(now - controller.since) : "—"}</dd>
        <dt>Controller drops</dt><dd class:bad={controller.drops > 0}>{controller.drops}</dd>
      </dl>
    </section>

    <section class="card">
      <h2>Trainer log</h2>
      <ol class="presses raw">
        {#each trainerLog as l, i (l.at + l.text + i)}
          <li><span class="muted">{l.at}</span> {l.text}</li>
        {:else}
          <li class="muted">Connect the trainer…</li>
        {/each}
      </ol>
    </section>
  </div>
</main>

<style>
  main { max-width: 1200px; margin: 0 auto; padding: 1.25rem; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
  h1 { margin: 0; font-weight: 600; display: flex; align-items: center; gap: 0.6rem; }
  h1 small { color: var(--muted); font-weight: 400; font-size: 0.55em; }
  h2 { margin: 0 0 0.25rem; font-size: 1rem; font-weight: 600; display: flex; align-items: center; gap: 0.5rem; }
  .actions { display: flex; gap: 0.5rem; }
  .card { background: var(--surface); border-radius: var(--radius); padding: 1rem 1.25rem; margin-top: 1rem; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 0 1rem; }
  .muted { color: var(--muted); }
  .error { color: var(--bad); background: var(--surface); padding: 0.75rem 1rem; border-radius: var(--radius); }
  .dot { width: 0.6rem; height: 0.6rem; border-radius: 50%; background: var(--bad); }
  .dot.on { background: var(--ok); }
  .found { list-style: none; padding: 0; margin: 0.5rem 0 0; }
  .found li { display: grid; grid-template-columns: 7rem 1fr 5rem auto; gap: 0.75rem; align-items: center; padding: 0.35rem 0; }
  .kind { color: var(--accent); font-size: 0.85rem; }
  .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; margin: 0.75rem 0; }
  .metrics div, .target { display: flex; flex-direction: column; align-items: center; background: var(--surface-2); border-radius: 10px; padding: 0.6rem; }
  .metrics b { font-size: 1.8rem; font-variant-numeric: tabular-nums; }
  .metrics span, .target span { color: var(--muted); font-size: 0.8rem; }
  .erg { display: flex; align-items: center; gap: 0.5rem; }
  .target { flex: 1; }
  .target b { font-size: 2.2rem; color: var(--accent); font-variant-numeric: tabular-nums; }
  .presses { list-style: none; padding: 0; margin: 0.5rem 0; min-height: 8rem; }
  .presses li { padding: 0.15rem 0; }
  .battery { margin-left: auto; font-weight: 400; font-size: 0.9rem; color: var(--muted); }
  .battery.low { color: var(--warn); }
  .small { font-size: 0.8rem; margin: 0.5rem 0 0.25rem; }
  ul.raw { list-style: none; padding: 0; margin: 0; }
  .raw { font-family: ui-monospace, monospace; font-size: 0.8rem; overflow-wrap: anywhere; }
  dl { display: grid; grid-template-columns: auto 1fr; gap: 0.4rem 1rem; margin: 0.5rem 0 0; }
  dt { color: var(--muted); }
  dd { margin: 0; font-variant-numeric: tabular-nums; }
  dd.bad { color: var(--bad); }
</style>
