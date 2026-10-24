#!/usr/bin/env node
// 检查 JS 里 $('xxx') 引用的 ID 是否在 HTML 中存在
const fs = require('fs');
const html = fs.readFileSync(__dirname + '/index.html', 'utf8');

// 提取 HTML 里所有 id="xxx"
const htmlIds = new Set();
for (const m of html.matchAll(/id="([a-zA-Z0-9_-]+)"/g)) htmlIds.add(m[1]);

// 提取 JS 里所有 $('xxx') 和 getElementById('xxx')
const jsIds = new Set();
const script = html.match(/<script>([\s\S]*?)<\/script>/);
if (script){
  for (const m of script[1].matchAll(/\$\('([a-zA-Z0-9_-]+)'\)/g)) jsIds.add(m[1]);
}

const missing = [...jsIds].filter(id => !htmlIds.has(id));
console.log(`HTML 中定义 ${htmlIds.size} 个 ID，JS 引用 ${jsIds.size} 个`);
if (missing.length){
  console.log('\n❌ 以下 ID 在 JS 里被引用但 HTML 中不存在：');
  missing.forEach(id => console.log('   -', id));
  process.exit(1);
} else {
  console.log('✅ 所有引用都存在');
}
