var $=function(s){return document.querySelector(s)},S=null,esc=h;
function msg(t,ok){var m=$('#msg');m.className=ok?'ok':'bad';m.innerHTML=t}   /* t must already be escaped */
function sel(id,arr,ph){$(id).innerHTML=(ph?'<option value="">'+esc(ph)+'</option>':'')+arr.map(function(x){return'<option>'+esc(x)+'</option>'}).join('')}
function p2(n){return String(n).padStart(2,'0')}
function today(){var d=new Date();return d.getFullYear()+'-'+p2(d.getMonth()+1)+'-'+p2(d.getDate())}      /* always English digits */
function stamp(){var d=new Date();return today()+' '+p2(d.getHours())+':'+p2(d.getMinutes())}
function isIso(s){var m=/^(\d{4})-(\d{2})-(\d{2})$/.exec(s);if(!m)return false;var d=new Date(+m[1],+m[2]-1,+m[3]);return d.getFullYear()===+m[1]&&d.getMonth()===+m[2]-1&&d.getDate()===+m[3]}
function logTo(st,who,act,name){st.log.unshift({t:stamp(),who:who,act:act,name:name})}
function init(p){
  document.body.insertAdjacentHTML('afterbegin','<header><b>IP Generator and Tracker</b><nav>'+[['index','Main Page'],['generate','IP Generation'],['management','IP Management'],['worksheet','Worksheet']].map(function(a){return'<a href="'+a[0]+'.html"'+(a[0]===p?' class="on" aria-current="page"':'')+'>'+a[1]+'</a>'}).join('')+'</nav></header>');
  document.body.insertAdjacentHTML('beforeend','<footer>Test version with dummy rules. Always verify a real IP in the field (ping / arp) before using it.</footer>');
  document.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('a[href]');   /* smooth page change */
    if(!a||e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||a.target||!/\.html$/.test(a.getAttribute('href'))||(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches))return;
    e.preventDefault();document.body.classList.add('leaving');setTimeout(function(){location.href=a.href},140)});
  window.addEventListener('pageshow',function(){document.body.classList.remove('leaving')});
  return DB.load().then(function(s){S=s;return s},function(){msg('Browser storage is not available. Do not use a private window. Open the tool in a normal Edge or Chrome window.');return new Promise(function(){})});
}
