// Cross-attribution: show a line only when a camp overwhelmingly assigns an item
// to the OPPOSITE camp. A camp claiming an item as its own carries no tension.
export const XT_MIN_CAMP_VOTES = 25;
export const XT_CROSS_THRESHOLD = 0.7;

function share(item, camp, choice) {
  const decisive = (item[`xt_${camp}_left`] || 0) + (item[`xt_${camp}_right`] || 0);
  if (decisive < XT_MIN_CAMP_VOTES) return null;
  return { pct: (item[`xt_${camp}_${choice}`] || 0) / decisive, decisive };
}

export function crossAttributionLines(item) {
  const lines = [];
  const rightSaysLeft = share(item, "right", "left");
  if (rightSaysLeft && rightSaysLeft.pct > XT_CROSS_THRESHOLD) {
    lines.push(`${Math.round(rightSaysLeft.pct * 100)}% מהימנים חושבים שזה שמאלני`);
  }
  const leftSaysRight = share(item, "left", "right");
  if (leftSaysRight && leftSaysRight.pct > XT_CROSS_THRESHOLD) {
    lines.push(`${Math.round(leftSaysRight.pct * 100)}% מהשמאלנים חושבים שזה ימני`);
  }
  return lines;
}
