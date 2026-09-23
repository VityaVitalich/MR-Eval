// Run in the dashboard browser context.
function checkDynamicsSlope() {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const close = (a, b) => Math.abs(a - b) < 1e-10;
  const line = [{x: 0, y: 90}, {x: 20, y: 80}, {x: 100, y: 40}];
  const fit = dynamicsSlope(line);
  assert(close(fit.slope, -0.5) && fit.delta === -50 && fit.n === 3, 'Uneven checkpoint spacing');
  assert(close(dynamicsSlope(line.map(p => ({x: p.x * 20, y: p.y}))).slope, -0.025), 'Training sample scaling');
  const nonlinear = dynamicsSlope([{x: 0, y: 100}, {x: 10, y: 0}, {x: 100, y: 0}]);
  assert(close(nonlinear.slope, -55 / 91), 'Least-squares fit uses intermediate checkpoints');
  const bounded = dynamicsSlope(line, 20, 100);
  assert(bounded.n === 2 && bounded.start === 20 && bounded.end === 100, 'Inclusive fit window');
  assert(dynamicsSlope(line, 21, 99) === null && dynamicsSlope(line, 100, 100) === null, 'Insufficient checkpoints');
  assert(close(dynamicsSlope([...line, {x: 40, y: null}, {x: 60, y: NaN}]).slope, -0.5), 'Missing scores never become zero');
  assert(dynamicsSlope([{x: 0, y: 3}, {x: 100, y: 3}]).slope === 0, 'Flat trajectory');
  assert(dynamicsSlope([{x: 100, y: 20}, {x: 0, y: 0}]).slope === 0.2, 'Ascending trajectory and unsorted coordinates');
  for (const run of [() => dynamicsSlope(line, 20, 10), () => dynamicsSlope(line, NaN),
    () => dynamicsSlope([{x: 0, y: 1}, {x: 0, y: 2}])]) {
    let threw = false;
    try { run(); } catch { threw = true; }
    assert(threw, 'Invalid coordinates fail');
  }
  return { passed: 11 };
}
