function runTests(){
  var T=[],t=function(n,ok,d){T.push([n,!!ok,d||''])},id=1,r;
  r=build('HDGCP1-R1','Yokogawa',1);
  t('Hand-checked Yokogawa n=1: RTU 18.1.20.169 / 18.1.21.169',r['RTU IP-1']==='18.1.20.169'&&r['RTU IP-2']==='18.1.21.169');
  t('Hand-checked Yokogawa n=1: PLC .85, Internal .1, HMI .211, Moxa 18.1.10.1',r['PLC IP-1']==='18.1.20.85'&&r['RTU Internal IP-1']==='18.1.20.1'&&r['RTU-HMI IP']==='18.1.20.211'&&r['IES Moxa IP']==='18.1.10.1');
  r=build('SHGCP1-R1','Honeywell',1);
  t('Hand-checked Honeywell k=1: RTU 19.1.100.1, PLC-2 .4, HMI 19.1.101.1',r['RTU IP-1']==='19.1.100.1'&&r['PLC IP-2']==='19.1.100.4'&&r['RTU-HMI IP']==='19.1.101.1');
  t('Honeywell has no RTU Internal fields',!('RTU Internal IP-1' in r));
  var recs=[],full=[];
  Object.keys(CFG.gcps).forEach(function(g){CFG.vendors.forEach(function(v){
    for(var i=0;i<CFG.max[v];i++){var a=allocate(g,v,recs);if(a.full){full.push(g+v+' early');break}recs.push({id:id++,name:'T-'+id,gcp:g,vendor:v,ips:a.ips,del:false})}
    if(!allocate(g,v,recs).full)full.push(g+v+' not full')})});
  t('Every pool fills to its limit and then stops (no overflow)',full.length===0,full.join(', '));
  var seen={},dup=0,bad=0,cnt=0;recs.forEach(function(x){UNIQ.forEach(function(f){var ip=x.ips[f];if(!ip)return;cnt++;if(seen[ip])dup++;seen[ip]=1;
    var o=ip.split('.').map(Number);if(o.length!==4||o.some(function(y){return y<0||y>255})||o[3]<1||o[3]>249)bad++})});
  t('No duplicate IP across '+cnt+' generated addresses (all GCPs and vendors)',dup===0,dup+' duplicates');
  t('All hosts valid and never touch .250 / .253',bad===0,bad+' bad');
  var g='HDGCP1-R1',y=recs.filter(function(x){return x.gcp===g&&x.vendor==='Yokogawa'}),five=y[4];
  var rest=recs.filter(function(x){return x!==five}),a=allocate(g,'Yokogawa',rest);
  t('A freed number (permanent delete) is reused first',a.n===5);
  var tr=recs.map(function(x){return x===five?Object.assign({},x,{del:true}):x});
  t('A deleted record in the trash keeps its numbers reserved',allocate(g,'Yokogawa',tr).full===true);
  var base=[{id:1,name:'UTMN-1',ips:{'RTU IP-1':build('HDGCP1-R1','Yokogawa',1)['RTU IP-1']},del:false}],s=allocate('HDGCP1-R1','Yokogawa',base);
  t('An IP already used (e.g. imported) makes the tool skip that number',s.n===2&&s.skipped[0]===1);
  t('Same GCP and vendor in Ring 2 does not clash (different octet 2)',(function(){CFG.gcps['X-R2']=[18,2];CFG.vlan['X-R2']=['1','2'];var q=allocate('X-R2','Yokogawa',base);delete CFG.gcps['X-R2'];return q.n===1})());
  var nm=[{id:1,name:'UTMN-1000'}];
  t('Duplicate name is rejected (even with different letter case)',checkName('utmn-1000',nm)!==''&&checkName('UTMN-1001',nm)==='');
  t('Bad name formats are rejected',checkName('UTMN',nm)!==''&&checkName('ABCD-12',nm)!==''&&checkName('UTMN-12ab',nm)!=='');
  t('Editing a record does not clash with itself',checkName('UTMN-1000',nm,1)==='');
  return T;
}
