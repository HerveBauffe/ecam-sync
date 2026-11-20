// Typed wrappers around the Rust device commands and events (src-tauri/src/devices.rs).
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export type Kind = "trainer" | "controller" | "heartRate";
export type Button =
  | "shiftUp" | "shiftDown" | "up" | "down" | "left" | "right"
  | "a" | "b" | "y" | "z" | "powerUp" | "onOff";

export interface Found { address: string; name: string; kind: Kind; rssi: number | null }
export interface BikeData {
  speedKmh: number | null;
  cadenceRpm: number | null;
  powerW: number | null;
  hrBpm: number | null;
}
export interface Status { kind: Kind; connected: boolean; name: string; denied: boolean }
/** The trainer's answer to a control point command (`Reply` in velo-ble/src/ftms.rs). */
export type Reply = "success" | "denied" | "silent" | { failed: number };
export interface RawControllerMessage { hex: string; bitmap: string | null }

export const replyText = (r: Reply) => (typeof r === "string" ? r : `failed (0x${r.failed.toString(16)})`);

export const scan = (seconds = 5) => invoke<Found[]>("ble_scan", { seconds });
export const connectTrainer = (d: Found) =>
  invoke<boolean>("trainer_connect", { address: d.address, name: d.name });
export const connectController = (d: Found) =>
  invoke<void>("controller_connect", { address: d.address, name: d.name });
export const setPower = (watts: number) => invoke<Reply>("trainer_set_power", { watts });
export const freeRide = () => invoke<Reply>("trainer_free_ride");
export const disconnectAll = () => invoke<void>("ble_disconnect_all");

export const onTrainerData = (f: (d: BikeData) => void): Promise<UnlistenFn> =>
  listen<BikeData>("trainer:data", (e) => f(e.payload));
export const onButton = (f: (b: Button) => void): Promise<UnlistenFn> =>
  listen<{ button: Button }>("controller:button", (e) => f(e.payload.button));
export const onRaw = (f: (m: RawControllerMessage) => void): Promise<UnlistenFn> =>
  listen<RawControllerMessage>("controller:raw", (e) => f(e.payload));
export const onBattery = (f: (percent: number) => void): Promise<UnlistenFn> =>
  listen<{ percent: number }>("controller:battery", (e) => f(e.payload.percent));
export const onControlReply = (f: (op: string, reply: Reply) => void): Promise<UnlistenFn> =>
  listen<{ op: string; reply: Reply }>("trainer:control", (e) => f(e.payload.op, e.payload.reply));
export const onMachineStatus = (f: (text: string) => void): Promise<UnlistenFn> =>
  listen<{ text: string }>("trainer:status", (e) => f(e.payload.text));
export const onStatus = (f: (s: Status) => void): Promise<UnlistenFn> =>
  listen<Status>("device:status", (e) => f(e.payload));
