// Run in the dashboard browser context (functions from index.html).
function checkDynamicsBootstrap() {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const simple = dynamicsBootstrap([[0, 1], [100, 1]]);
  assert(simple.mean === 50 && simple.low === 0 && simple.high === 100, 'Two-question percentile interval');
  const weighted = dynamicsBootstrap([[0, 1], [100, 2]]);
  assert(weighted.mean === 100 / 3 && weighted.low === 0 && weighted.high === 50, 'Ratio of totals, not mean of ratios');
  const rows = Array.from({ length: 20 }, (_, i) => [i < 10 ? 'a' : 'b', i < 10 ? 0 : 100, 80]);
  const pairs = dynamicsEmPairs(rows, 'aligned_mean', null, null);
  const clustered = dynamicsBootstrap(pairs);
  const unclustered = dynamicsBootstrap(rows.map(r => [r[1], 1]));
  assert(clustered.low === 0 && clustered.high === 100, 'Question-level resampling');
  assert(unclustered.low > 0 && unclustered.high < 100, 'Response-level resampling understates uncertainty');
  assert(JSON.stringify(clustered) === JSON.stringify(dynamicsBootstrap(pairs)), 'Reproducible resampling');
  const filtered = dynamicsEmPairs([
    ['a', 0, 50], ['a', 100, 49], ['b', 80, 90], ['c', null, 80], ['d', 90, null],
  ], 'aligned_mean', 50, 90);
  assert(JSON.stringify(filtered) === JSON.stringify([[0, 1], [80, 1]]), 'Inclusive bounds; missing scores are not zeros');
  assert(dynamicsBootstrap([]).mean === null, 'Empty subset has no estimate');
  assert(dynamicsBootstrap([[3, 1]]).low === null, 'One question has no estimable CI');
  const constant = dynamicsBootstrap([[7, 1], [14, 2]]);
  assert(constant.mean === 7 && constant.low === 7 && constant.high === 7, 'Constant values have zero-width intervals');
  return { passed: 9 };
}
