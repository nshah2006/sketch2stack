export type ChatMsg = { id: string; from: 'user' | 'agent'; text: string }

export const SUGGESTIONS = ['Make it taller', 'Swap red for blue', 'Use fewer blocks', 'Why this build?']

const REPLIES: [RegExp, string][] = [
  [/tall/i, 'Added a second wall layer. Stability drops to 81%, still safe for the arm.'],
  [/swap|color|blue|red/i, 'Swapped all red bricks for blue. You have 2 blue bricks on the table, so I need 1 more.'],
  [/fewer|less|simple/i, 'Trimmed it to 5 blocks by merging the walls into planks.'],
  [/why/i, 'Your sketch has a pitched roof and a door gap, so I kept the triangle and left the center open.'],
]

export function mockReply(text: string) {
  for (const [re, reply] of REPLIES) if (re.test(text)) return reply
  return "Got it. I'll try that on the next interpretation (placeholder reply, agent not wired yet)."
}

export const VOICE_SCRIPT = {
  heard: 'Make the roof a little taller and use the green blocks.',
  reply: 'Raising the roof one layer and swapping the yellow cubes for green. Regenerating now.',
}
