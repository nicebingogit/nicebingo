// Pure bingo helpers shared across components.
export const LETTERS = ['B', 'I', 'N', 'G', 'O'];

export const cellKey = (letter, value) => `${letter}-${value}`;

export const isCalled = (letter, value, calledSet) =>
  value === 'FREE' || calledSet.has(cellKey(letter, value));

// Returns { patterns: string[], cells: [col,row][] } for one card.
export function checkPatterns(cardNumbers, calledSet) {
  const patterns = [];
  const cells = new Set();
  const hit = (c, r) => isCalled(LETTERS[c], cardNumbers[LETTERS[c]][r], calledSet);

  for (let r = 0; r < 5; r++) {
    if ([0, 1, 2, 3, 4].every((c) => hit(c, r))) {
      patterns.push('Row');
      [0, 1, 2, 3, 4].forEach((c) => cells.add(`${c},${r}`));
    }
  }
  for (let c = 0; c < 5; c++) {
    if ([0, 1, 2, 3, 4].every((r) => hit(c, r))) {
      patterns.push('Column');
      [0, 1, 2, 3, 4].forEach((r) => cells.add(`${c},${r}`));
    }
  }
  if ([0, 1, 2, 3, 4].every((i) => hit(i, i))) {
    patterns.push('Diagonal');
    [0, 1, 2, 3, 4].forEach((i) => cells.add(`${i},${i}`));
  }
  if ([0, 1, 2, 3, 4].every((i) => hit(4 - i, i))) {
    patterns.push('Anti-Diagonal');
    [0, 1, 2, 3, 4].forEach((i) => cells.add(`${4 - i},${i}`));
  }
  const corners = [[0, 0], [4, 0], [0, 4], [4, 4]];
  if (corners.every(([c, r]) => hit(c, r))) {
    patterns.push('Four Corners');
    corners.forEach(([c, r]) => cells.add(`${c},${r}`));
  }
  return {
    patterns,
    cells: [...cells].map((s) => s.split(',').map(Number)),
  };
}

export const PATTERN_LABELS = {
  Row: 'Complete Row',
  Column: 'Complete Column',
  Diagonal: 'Main Diagonal',
  'Anti-Diagonal': 'Anti Diagonal',
  'Four Corners': 'Four Corners',
};
