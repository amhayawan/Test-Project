(login) => {
const NAMES = {admin:["مدير النظام","System administrator"],director:["د. سامية فؤاد","Dr. Samia Fouad"],casemanager:["منى عبد الحميد","Mona Abdelhamid"],projects:["شريف منير","Sherif Mounir"],researcher1:["أحمد سعيد","Ahmed Saeed"],researcher2:["هبة محمود","Heba Mahmoud"],fundraiser:["كريم يوسف","Karim Youssef"],hrmanager:["نادية حسن","Nadia Hassan"],hrofficer:["ياسمين علي","Yasmine Ali"],payroll:["طارق فهمي","Tarek Fahmy"],sara:["سارة إبراهيم","Sara Ibrahim"],finmanager:["حسام الدين رشاد","Hossam Rashad"],accountant:["مروة شوقي","Marwa Shawky"],procurement:["عمرو جلال","Amr Galal"],storekeeper:["محمد عبد الله","Mohamed Abdallah"],pm:["رانيا عادل","Rania Adel"]};
const depts = DEPTS.filter(d => !d.hidden);
const home = (depts.find(d => d.logins.includes(login)) || {name: "Management"}).name;
const mentions = (s, u) => s.includes(`<span class="login">${u}</span>`);
const LOGINS = Object.keys(LOGIN_ROLE);

// who acts in each step: "As X" / "Sign in as X" switches the actor; "as X" later in a step adds X
function actors(c) {
  let cur = c.who[0] === "any login" ? login : c.who[0];
  return c.steps.map(([d]) => {
    const lead = d.match(/^(?:Sign out\. )?(?:As|Sign in as) <span class="login">([a-z0-9]+)<\/span>/);
    if (lead) cur = lead[1];
    const set = new Set([cur]);
    for (const u of LOGINS) if (new RegExp(`as <span class="login">${u}</span>`).test(d)) set.add(u);
    if (c.id.startsWith("E2E")) return ["group"];
    return [...set];
  });
}

const mine = [];
for (const d of depts) for (const c of d.cases) {
  const inWho = c.who.includes(login) || c.who.includes("any login");
  const inSteps = c.steps.some(s => mentions(s[0], login));
  if (inWho || inSteps) mine.push({...c, dept: d});
}
if (login === "admin") mine.push({...ACCESS_CASE, dept: {name: "Access checks"}});
const total = mine.reduce((a, c) => a + c.min, 0);

const box = '<span class="bx"></span>';
const opts = list => list.map(x => `<span class="opt">${box}${x}</span>`).join("");
const sees = SEES[login];
const menu = sees ? GROUPS.map((g, i) => `<tr><td><span class="ar">${g}</span></td><td class="c">${sees[i] ? "Must be visible" : "Must be hidden"}</td><td class="c">${opts(["As expected","Wrong"])}</td></tr>`).join("")
  : `<tr><td colspan="3">No module groups. Only the leave and payroll rules you sign off, plus ${A("لوحة التحكم")}, ${A("الاعتمادات")}, ${A("إجازاتي")}, ${A("قسائم راتبي")}.</td></tr>`;

const caseHTML = c => {
  const act = actors(c);
  const rows = c.steps.map((s, i) => {
    const a = act[i], yours = a.includes(login) || a[0] === "group";
    return `<tr class="${yours ? "" : "other"}"><td class="n">${i + 1}</td><td>${s[0]}</td><td class="ex">${s[1]}</td>
      <td class="by">${a[0] === "group" ? "Group" : a.map(u => u === login ? "<b>You</b>" : `<span class="login">${u}</span>`).join(" ")}</td>
      <td class="res"><span class="rb">${box}W</span><span class="rb">${box}H</span><span class="rb">${box}F</span></td></tr>`;
  }).join("");
  return `<section class="case">
   <div class="ch"><span class="cid">${c.id}</span><h3>${c.t}</h3><span class="tm">${c.dept.name} · target ${c.min} min${c.neg ? " · <b>must be refused</b>" : ""}</span></div>
   <p class="why"><b>Goal.</b> ${c.why}</p>
   ${c.pre ? `<p class="pre"><b>Before you start.</b> ${c.pre}</p>` : ""}
   ${c.flow ? `<p class="pre"><b>Order.</b> ${c.flow.join(" → ")}</p>` : ""}
   <table class="steps"><thead><tr><th>#</th><th>Do this</th><th>You should see</th><th>By</th><th class="res">Result</th></tr></thead><tbody>${rows}</tbody></table>
   ${c.ask ? `<p class="ask">${c.ask}</p>` : ""}
   <table class="score">
    <tr><th>Minutes taken</th><td><span class="line short"></span> (target ${c.min})</td><th>Ease</th><td>${opts(["1","2","3","4","5"])}<span class="hint">1 = very hard · 5 = very easy</span></td></tr>
    <tr><th>Help needed</th><td colspan="3">${opts(["None","One hint","Guided through","Observer took over"])}</td></tr>
    <tr><th>Matches our process?</th><td>${opts(["Yes","Partly","No"])}</td><th>Worst problem</th><td>${opts(["None","S3","S2","S1"])}</td></tr>
    <tr><th>Notes</th><td colspan="3"><span class="line"></span><span class="line"></span><span class="line"></span></td></tr>
   </table></section>`;
};

const [ar, en] = NAMES[login];
return `<!doctype html><html><head><meta charset="utf-8"><title>HAZ-v2 test guide – ${login}</title>
<link rel="stylesheet" href="fonts/local.css">
<style>
@page{size:A4;margin:14mm 13mm 16mm}
:root{--ink:#17231e;--muted:#5b6b63;--line:#c9d6cf;--green:#13795b;--deep:#0f3d31;--tint:#e6f2ec;--soft:#f3f6f4}
*{box-sizing:border-box}
body{margin:0;font:9.6pt/1.45 "IBM Plex Sans","Noto Kufi Arabic",sans-serif;color:var(--ink);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.ar{font-family:"Noto Kufi Arabic",sans-serif;direction:rtl;unicode-bidi:isolate;background:var(--tint);padding:0 3px;border-radius:3px;font-size:.92em}
.login{font:500 .86em "IBM Plex Mono",monospace;background:var(--soft);border:1px solid var(--line);padding:0 4px;border-radius:3px;white-space:nowrap}
code{font:500 .92em "IBM Plex Mono",monospace}
h1,h2,h3{margin:0;line-height:1.25}
.cover{background:var(--deep);color:#fff;border-radius:8px;padding:16px 18px;display:grid;grid-template-columns:1fr auto;gap:6px 20px}
.cover .eb{font-size:8pt;letter-spacing:.08em;text-transform:uppercase;color:#9fd8c2;grid-column:1/-1}
.cover h1{font-size:19pt}
.cover .who{font-size:11pt;color:#d5ebe1}
.cover .who .arn{font-family:"Noto Kufi Arabic";direction:rtl;unicode-bidi:isolate}
.cred{background:#fff;color:var(--ink);border-radius:6px;padding:8px 12px;align-self:start;grid-row:2/4;grid-column:2;font-size:9pt}
.cred div{display:flex;justify-content:space-between;gap:14px}
.cred b{font:600 10pt "IBM Plex Mono",monospace}
.meta{display:grid;grid-template-columns:repeat(3,1fr);gap:10px 18px;margin:12px 0 4px}
.meta div{border-bottom:1px solid var(--ink);padding-top:14px;font-size:8pt;color:var(--muted);position:relative}
.meta span{position:absolute;top:0;left:0}
h2{font-size:12.5pt;color:var(--deep);margin:14px 0 6px;padding-bottom:3px;border-bottom:2px solid var(--green)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px 18px}
ol,ul{margin:0;padding-left:16px}
li{margin:2px 0}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;vertical-align:top;padding:4px 6px;border:1px solid var(--line)}
th{background:var(--soft);font-size:7.8pt;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
td.c{text-align:center}
.sev{font:600 8pt "IBM Plex Mono",monospace;padding:0 4px;border-radius:3px}
.list td.num{text-align:right;font-variant-numeric:tabular-nums}
.bx{display:inline-block;width:9px;height:9px;border:1.2px solid var(--ink);border-radius:2px;vertical-align:-1px;margin-right:4px}
.opt{white-space:nowrap;margin-right:12px}
.case{margin-top:16px;padding-top:4px}
.ch,.why,.pre{break-after:avoid}
.ch{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;align-items:baseline;border-bottom:2px solid var(--green);padding-bottom:5px;margin-bottom:6px}
.cid{font:600 11pt "IBM Plex Mono",monospace;color:var(--green)}
.ch h3{font-size:13pt}
.tm{grid-column:2;font-size:8.5pt;color:var(--muted)}
.why,.pre,.ask{margin:4px 0 7px}
.pre{background:var(--soft);border:1px dashed var(--line);border-radius:5px;padding:5px 8px}
.ask{border-left:3px solid var(--green);background:var(--tint);padding:5px 9px}
.steps td{font-size:9.2pt}
.steps tr{break-inside:avoid}
.steps .n{width:22px;font:600 8.5pt "IBM Plex Mono",monospace;color:var(--muted);text-align:center}
.steps .ex{color:#33443c;width:34%}
.steps .by{width:74px;font-size:8.3pt}
.steps .res,.steps th.res{width:44px;font-size:8pt;font-weight:600}
.rb{display:block;white-space:nowrap;line-height:1.5}
.steps tr.other td:not(.res){color:#7d8b84}
.steps tr.other .ar{background:#eef2f0}
.score{margin-top:8px;break-inside:avoid}
.score th{width:17%;text-transform:none;letter-spacing:0;font-size:8.5pt;color:var(--ink)}
.line{display:block;border-bottom:1px solid #9fb0a7;height:17px}
.line.short{display:inline-block;width:60px;height:12px}
.hint{display:block;font-size:7.5pt;color:var(--muted)}
.final{break-before:page}
.q td:last-child{white-space:nowrap}
.sign{display:grid;grid-template-columns:1fr 1fr 1fr;gap:20px;margin-top:22px}
.sign div{border-top:1px solid var(--ink);padding-top:3px;font-size:8pt;color:var(--muted)}
.note{font-size:8pt;color:var(--muted)}
</style></head><body>
<div class="cover">
  <div class="eb">Dr. Hassan Abbas Zaki Association · HAZ-v2 user testing</div>
  <h1>Test guide: ${LOGIN_ROLE[login]}</h1>
  <div class="who">Demo person: ${en} · <span class="arn">${ar}</span> · ${home}</div>
  <div class="cred"><div><span>Username</span><b>${login}</b></div><div><span>Password</span><b>${PW}</b></div></div>
</div>
<div class="meta"><div><span>Tester (real name)</span></div><div><span>Job title</span></div><div><span>Date</span></div><div><span>Observer</span></div><div><span>PC / location</span></div><div><span>Round</span></div></div>

<h2>How this test works</h2>
<div class="two">
 <div><ol>
  <li>You use the system; the observer writes. Say aloud what you are looking for and what you expect.</li>
  <li>Read only the case title and goal first, then try it yourself. Use the steps when you are stuck, and tell the observer.</li>
  <li>The observer helps only after 2 minutes stuck. Any help is recorded. This tests the system, not you.</li>
  <li>Grey steps are done by another login (shown under "By"). Watch them or skip them, as the observer says.</li>
 </ol></div>
 <div><ul>
  <li><b>W, Works</b>: done, result as described.</li>
  <li><b>H, Hard</b>: done, but confusing, slow or you hesitated.</li>
  <li><b>F, Fails</b>: wrong result, an error, or could not finish.</li>
  <li>A case <b>passes</b> when every step works with no S1 or S2, with no help or one hint, in up to 1.5× the target time, ease 4 or 5, and it matches how you work.</li>
 </ul></div>
</div>
<table style="margin-top:8px"><thead><tr><th style="width:9%">Level</th><th>Meaning</th><th style="width:38%">Example</th></tr></thead><tbody>
 <tr><td><b>S1</b></td><td>Blocks the work, wrong money, or data seen by the wrong person</td><td>A researcher sees a donor's amount</td></tr>
 <tr><td><b>S2</b></td><td>Finished only with help or a workaround</td><td>Cannot find where approved cases go</td></tr>
 <tr><td><b>S3</b></td><td>Works, but confusing wording or layout</td><td>An unclear button label</td></tr>
</tbody></table>

<h2>Your cases (${mine.length}) · about ${Math.round(total / 5) * 5} minutes</h2>
<table class="list"><thead><tr><th style="width:12%">Case</th><th>Title</th><th style="width:22%">Department</th><th style="width:11%">Target</th><th style="width:13%">Result</th></tr></thead><tbody>
${mine.map(c => `<tr><td><b>${c.id}</b></td><td>${c.t}</td><td>${c.dept.name}</td><td class="num">${c.min} min</td><td>${box}Pass ${box}Fail</td></tr>`).join("")}
</tbody></table>
<p class="note">Run the cases in this order: later cases use records made by earlier ones. Start from fresh demo data (${A("تحميل البيانات التجريبية")} on first start). Demo people and figures are fictional; tax, insurance and leave values are SAMPLE DATA, not legal values.</p>

<h2>Your menu check (do this first)</h2>
<p class="note" style="margin:0 0 5px">After signing in, compare the side menu with this list. Seeing a group you should not is an S1.</p>
<table><thead><tr><th>Menu group</th><th class="c" style="width:28%">Rule for ${login}</th><th class="c" style="width:30%">What you saw</th></tr></thead><tbody>${menu}</tbody></table>
${NOTE[login] ? `<p class="note">Inside your modules: ${NOTE[login]}.</p>` : ""}

${mine.map(caseHTML).join("")}

<section class="final">
<h2>Your overall view</h2>
<p class="note" style="margin:0 0 6px">Circle one per line: 1 = strongly disagree, 5 = strongly agree.</p>
<table class="q"><tbody>
${["I could do my daily work in this system without asking someone.","It is faster than the way we work today (paper, Excel, phone).","The Arabic wording on the screens is clear.","I trust that people who should not see my department's data cannot see it.","I would be comfortable using this every day."].map((q, i) => `<tr><td style="width:4%">${i + 1}</td><td>${q}</td><td>${opts(["1","2","3","4","5"])}</td></tr>`).join("")}
</tbody></table>
<h2>Three things to change</h2>
<p class="note" style="margin:0 0 4px">The screens or steps that were the most confusing or slow, in order.</p>
<span class="line"></span><span class="line"></span><span class="line"></span><span class="line"></span><span class="line"></span><span class="line"></span>
<h2>What is missing for your job?</h2>
<span class="line"></span><span class="line"></span><span class="line"></span><span class="line"></span>
<div class="sign"><div>Tester signature</div><div>Observer signature</div><div>Department manager</div></div>
</section>
</body></html>`;
}
