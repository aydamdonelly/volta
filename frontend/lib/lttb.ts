// LTTB (Largest Triangle Three Buckets) — Sveinn Steinarsson 2013
// Downsample {ts:string, value:number}[] to ~target points while preserving visual shape.
export function downsample<P extends { ts: string; value: number }>(points: P[], target: number = 200): P[] {
  if (target >= points.length || target < 3) return points;
  const sampled: P[] = [];
  const bucketSize = (points.length - 2) / (target - 2);
  sampled.push(points[0]);
  let a = 0;
  for (let i = 0; i < target - 2; i++) {
    // Average of next bucket
    const avgRangeStart = Math.floor((i + 1) * bucketSize) + 1;
    const avgRangeEnd = Math.min(Math.floor((i + 2) * bucketSize) + 1, points.length);
    let avgX = 0, avgY = 0;
    const avgRangeLength = avgRangeEnd - avgRangeStart;
    for (let j = avgRangeStart; j < avgRangeEnd; j++) {
      avgX += new Date(points[j].ts).getTime();
      avgY += points[j].value;
    }
    avgX /= avgRangeLength; avgY /= avgRangeLength;
    // Pick point in current bucket that yields largest triangle area
    const rangeStart = Math.floor(i * bucketSize) + 1;
    const rangeEnd = Math.floor((i + 1) * bucketSize) + 1;
    const pAx = new Date(points[a].ts).getTime();
    const pAy = points[a].value;
    let maxArea = -1, nextA = rangeStart;
    for (let j = rangeStart; j < rangeEnd; j++) {
      const area = Math.abs(
        (pAx - avgX) * (points[j].value - pAy) -
          (pAx - new Date(points[j].ts).getTime()) * (avgY - pAy),
      ) * 0.5;
      if (area > maxArea) { maxArea = area; nextA = j; }
    }
    sampled.push(points[nextA]);
    a = nextA;
  }
  sampled.push(points[points.length - 1]);
  return sampled;
}
