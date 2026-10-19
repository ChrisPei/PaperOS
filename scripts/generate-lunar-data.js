// Factual month boundaries from Node ICU; only offline C data ships to Kindle.
const fs = require('node:fs');
const path = require('node:path');
const formatter = new Intl.DateTimeFormat('en-u-ca-chinese', {
  year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC'
});
const rows = [];
for (let stamp=Date.UTC(1900,0,1);stamp<Date.UTC(2101,2,1);stamp+=86400000) {
  const p=Object.fromEntries(formatter.formatToParts(new Date(stamp)).map(x=>[x.type,x.value]));
  if (+p.day===1) rows.push('    {'+[stamp/86400000,p.relatedYear,parseInt(p.month),p.month.includes('bis')?1:0].join(',')+'},');
}
const out = path.join(__dirname,'..','native','lunar-data.h');
fs.writeFileSync(out, '/* Gregorian/lunar month boundaries, Node ICU Chinese calendar. */\n'
 + 'static const struct { int day; short year; unsigned char month,leap; } lunar_months[] = {\n'
 + rows.join('\n')+'\n};\n');
console.log(rows.length+' lunar month boundaries -> '+out);
