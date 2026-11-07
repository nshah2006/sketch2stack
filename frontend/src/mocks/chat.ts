export type ChatMsg = { id: string; from: 'user' | 'agent'; text: string }

// Placeholder until voice is wired (next step).
export const VOICE_SCRIPT = {
  heard: 'Make the roof a little taller and use the green blocks.',
  reply: 'Raising the roof one layer and swapping the yellow cubes for green. Regenerating now.',
}
