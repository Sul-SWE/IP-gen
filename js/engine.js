/* Generator + validator. No UI and no storage here, so it can move to a server later. */
var UNIQ=['RTU IP-1','RTU IP-2','PLC IP-1','PLC IP-2','RTU Internal IP-1','RTU Internal IP-2','RTU-HMI IP','IES Moxa IP'];
var ALLF=['RTU IP-1','RTU IP-2','PLC IP-1','PLC IP-2','RTU Internal IP-1','RTU Internal IP-2','RTU-HMI IP','Engg. Laptop IP','IES Moxa IP','Gateway-1','Gateway-2','Subnet Mask','RTU VLAN','PLC VLAN'];
function build(gcp,vendor,n){
  var g=CFG.gcps[gcp],p=g[0]+'.'+g[1]+'.',v=CFG.vlan[gcp],r;
  if(vendor==='Yokogawa'){var A=p+'20.',B=p+'21.';
    r={'RTU IP-1':A+(n+168),'RTU IP-2':B+(n+168),'PLC IP-1':A+(n+84),'PLC IP-2':B+(n+84),
       'RTU Internal IP-1':A+n,'RTU Internal IP-2':B+n,'RTU-HMI IP':A+(n+210),'IES Moxa IP':p+'10.'+n,
       'Engg. Laptop IP':A+250,'Gateway-1':A+253,'Gateway-2':B+253};
  }else{var s=4*(n-1)+1;A=p+'100.';B=p+'101.';
    r={'RTU IP-1':A+s,'RTU IP-2':A+(s+1),'PLC IP-1':A+(s+2),'PLC IP-2':A+(s+3),
       'RTU-HMI IP':B+n,'IES Moxa IP':p+'11.'+n,'Engg. Laptop IP':A+250,'Gateway-1':A+253,'Gateway-2':B+253};
  }
  r['Subnet Mask']=CFG.mask;r['RTU VLAN']=v[0];r['PLC VLAN']=v[1];return r;
}
// every unique IP in use (deleted records still count: they stay reserved)
function taken(recs,skipId){var m={};recs.forEach(function(r){if(r.id!==skipId)UNIQ.forEach(function(f){if(r.ips[f])m[r.ips[f]]=r.name})});return m}
function allocate(gcp,vendor,recs,skipId){
  var t=taken(recs,skipId),skipped=[];
  for(var n=1;n<=CFG.max[vendor];n++){var ips=build(gcp,vendor,n);
    if(!UNIQ.some(function(f){return ips[f]&&t[ips[f]]}))return{n:n,ips:ips,skipped:skipped};
    skipped.push(n)}
  return{full:true,skipped:skipped};
}
function usage(gcp,vendor,recs){
  var t=taken(recs),free=0,m=CFG.max[vendor];
  for(var n=1;n<=m;n++){var ips=build(gcp,vendor,n);if(!UNIQ.some(function(f){return ips[f]&&t[ips[f]]}))free++}
  return{used:m-free,max:m};
}
function h(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function checkName(name,recs,skipId){
  name=String(name).trim().toUpperCase();
  if(!/^[A-Z]{4}-\d{1,5}$/.test(name)||CFG.facilities.indexOf(name.split('-')[0])<0)return 'Name must look like UTMN-1000: a facility from the list, a dash, then the well number.';
  return recs.some(function(r){return r.id!==skipId&&r.name.toUpperCase()===name})?('The name '+h(name)+' already exists.'):'';
}
function checkIps(ips,recs,skipId){
  var t=taken(recs,skipId),e=[];
  UNIQ.forEach(function(f){if(ips[f]&&t[ips[f]])e.push(h(f+' '+ips[f])+' is already used by '+h(t[ips[f]]))});return e;
}
function rowOf(r){var o={'Facility Name':r.name,'GCP & Ring':r.gcp,'Vendor':r.vendor,'Date':r.date,'TSU PAN Engineer':r.engineer};ALLF.forEach(function(f){o[f]=r.ips[f]||''});return o}
