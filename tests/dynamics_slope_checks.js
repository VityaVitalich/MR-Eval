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

function checkDynamicsLocalRates() {
  const assert = (ok, message) => { if (!ok) throw new Error(message); };
  const close = (a, b) => Math.abs(a - b) < 1e-10;
  const values = rates => rates.map(p => p.y);
  const line = [0, 10, 30, 60, 100].map(x => ({x, y: 100 - 0.5*x}));
  for (const method of ['previous', 'centered', 'fit']) {
    const rates = dynamicsLocalRates(line, method);
    assert(rates.filter(p => p.y !== null).every(p => close(p.y, -0.5)), 'Uneven spacing: '+method);
    assert(rates[0].y === null, 'No edge substitution: '+method);
    if (method !== 'previous') assert(rates[4].y === null, 'No trailing edge substitution');
  }
  assert(JSON.stringify(values(dynamicsLocalRates(line, 'fit', 5))) === JSON.stringify([null,null,-0.5,null,null]), 'Full five-checkpoint fit');
  const nonlinear = [{x:0,y:100},{x:10,y:0},{x:100,y:0}];
  assert(close(dynamicsLocalRates(nonlinear, 'centered')[1].y, -1), 'Centered secant');
  assert(close(dynamicsLocalRates(nonlinear, 'fit')[1].y, -55/91), 'Local regression differs from centered secant');
  const gap = line.map((p,i) => ({...p,y:i===2?null:p.y}));
  assert(JSON.stringify(values(dynamicsLocalRates(gap,'previous'))) === JSON.stringify([null,-0.5,null,null,-0.5]), 'No crossing a missing score');
  assert(dynamicsLocalRates(gap,'centered').every(p=>p.y===null), 'Centered support requires scored center');
  assert(dynamicsLocalRates(line.slice(0,2),'fit').every(p=>p.y===null), 'Two checkpoints cannot supply a local fit');
  const bounded = dynamicsLocalRates(line,'previous',3,10,60);
  assert(bounded.length===3 && bounded[0].y===null && bounded[1].start===10, 'Range limits the entire support');
  const recovery = dynamicsLocalRates([{x:0,y:100},{x:10,y:0},{x:20,y:100}],'previous');
  assert(dynamicsRateAggregate(recovery,'decline').value===5, 'Recovery does not cancel decline');
  assert(dynamicsRateAggregate(recovery,'rise').value===5, 'Rise magnitude');
  assert(dynamicsRateAggregate(recovery,'absolute').value===10, 'Absolute movement');
  assert(dynamicsRateAggregate(recovery,'mean').value===0 && dynamicsRateAggregate(recovery,'median').value===0, 'Signed summaries can cancel');
  assert(dynamicsRateAggregate([{y:0},{y:1},{y:100}],'median').value===1, 'Median resists extreme slope');
  assert(dynamicsRateAggregate([{y:null}],'decline')===null, 'Missing is not zero');
  assert(dynamicsRateAggregate([{y:0},{y:2}],'decline').value===0, 'No decline has zero magnitude');
  for (const run of [()=>dynamicsLocalRates(line,'fit',4),()=>dynamicsLocalRates(line,'bad'),
    ()=>dynamicsLocalRates([{x:NaN,y:1}],'previous'),()=>dynamicsRateAggregate([],'bad')]) {
    let threw=false;try{run()}catch{threw=true}assert(threw,'Invalid configuration fails');
  }
  return {passed:24};
}
