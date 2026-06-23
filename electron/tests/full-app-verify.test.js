const http=require('http');const fs=require('fs');const path=require('path');const{spawn}=require('child_process')
const P='\x1b[32mPASS\x1b[0m',F='\x1b[31mFAIL\x1b[0m';let p=0,f=0
function a(c,m){if(c){console.log(`  ${P} ${m}`);p++}else{console.log(`  ${F} ${m}`);f++}}
const APP=process.env.LIANGHUA_APP_PATH || path.join(__dirname, '..', '..', 'release', 'mac', 'LiangHua.app')
const R=path.join(APP,'Contents','Resources')
async function sleep(ms){return new Promise(r=>setTimeout(r,ms))}
async function healthCheck(port){try{return await new Promise((resolve)=>{http.get(`http://127.0.0.1:${port}/api/v1/health`,(res)=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>resolve(JSON.parse(d)))}).on('error',()=>resolve(null))})}catch{return null}}
async function run(){
// Skip if app not built
if(!fs.existsSync(APP)){console.log(`\n=== TDD: 完整 App 启动验证 (SKIPPED: ${APP} not found) ===`);console.log(`设置 LIANGHUA_APP_PATH 环境变量指向已打包的 .app 路径`);return}
console.log('\n=== TDD: 完整 App 启动验证 ===')
console.log('\n[测试1] App 结构完整性')
a(fs.existsSync(path.join(R,'frontend','index.html')),'frontend/index.html 存在')
a(fs.existsSync(path.join(R,'backend','dist','lianghua-backend')),'backend/dist/lianghua-backend 存在')
a(fs.existsSync(path.join(APP,'Contents','MacOS','LiangHua')),'Electron 可执行文件存在')
a(fs.existsSync(path.join(APP,'Contents','Resources','app.asar')),'app.asar 存在')
console.log('\n[测试2] 前端文件完整性')
const html=fs.readFileSync(path.join(R,'frontend','index.html'),'utf-8')
a(html.includes('root'),'index.html 包含 root 挂载点')
a(html.includes('assets'),'index.html 引用 assets')
a(fs.existsSync(path.join(R,'frontend','assets')),'assets 目录存在')
console.log('\n[测试3] 后端二进制可执行')
const bin=path.join(R,'backend','dist','lianghua-backend')
const st=fs.statSync(bin)
a(!!(st.mode&0o111),'有执行权限')
a(st.size>90000000,`大小合理: ${(st.size/1024/1024).toFixed(0)}MB`)
console.log('\n[测试4] 后端启动+健康检查(最长等待120s)')
const proc=spawn(bin,['--host','127.0.0.1','--port','18770'],{timeout:180000})
let ok=false;const t0=Date.now()
for(let i=0;i<120;i++){await sleep(1000);const h=await healthCheck(18770);if(h&&h.status==='ok'){ok=true;a(true,`健康检查成功 (${Math.round((Date.now()-t0)/1000)}s, status=${h.status})`);break}}
if(!ok){const h=await healthCheck(18770);a(false,'健康检查失败，日志:'+(h?JSON.stringify(h):'无响应'))}
try{proc.kill()}catch{}
console.log('\n[测试5] 前端内容验证')
a(html.includes('LiangHua')||html.includes('lianghua'),'index.html 包含应用名称')
console.log(`\n${'='.repeat(50)}\n结果: ${p} 通过, ${f} 失败, ${p+f} 总计`)
if(f>0)process.exit(1)}
run().catch(e=>{console.error('ERROR:',e);process.exit(1)})