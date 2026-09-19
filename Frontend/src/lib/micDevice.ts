/**
 * Which microphone this tab actually listens on.
 *
 * The Web Speech API has no device selector. `SpeechRecognition` records whatever the browser
 * considers the tab's input and ignores any property an app sets, so the choice cannot be passed
 * to it — it can only be made true. What it does respect is a live getUserMedia stream: while the
 * tab holds one open on a device, recognition records from that device too. So picking a
 * microphone in settings means holding a stream on it for as long as we are listening, and
 * letting go when we stop.
 *
 * The Python microphone is a separate question with a separate answer. Browser device ids are
 * opaque per-origin hashes that mean nothing outside the tab, so the human-readable label is what
 * travels to windows/speech.py — see SettingsPanel, which sends the label alongside the id.
 */
let held: MediaStream | null = null;

/** Hold `deviceId` open so recognition uses it. "" falls back to the system default. */
export async function holdMicDevice(deviceId: string): Promise<void> {
  releaseMicDevice();
  if (!deviceId || typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return;
  }
  try {
    held = await navigator.mediaDevices.getUserMedia({
      audio: { deviceId: { exact: deviceId } },
    });
  } catch {
    // A device chosen earlier and unplugged since is not worth reporting: the tab simply falls
    // back to the system default, which is what it would have used anyway.
    held = null;
  }
}

/** Let go of the held device. Safe to call when nothing is held. */
export function releaseMicDevice(): void {
  held?.getTracks().forEach((track) => track.stop());
  held = null;
}
