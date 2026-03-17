#!/usr/bin/env node
// SPDX-FileCopyrightText: 2025 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0
const http = require("http");
const assert = require("assert");
const path = require("path");
const INGRESS_PATH = "/api/hassio_ingress/TEST_TOKEN_123";
let passed = 0, failed = 0;
function test(name, fn) {
  try { fn(); passed++; console.log("  PASS " + name); }
  catch (e) { failed++; console.log("  FAIL " + name + ": " + e.message); }
}
function countRawNext(text) {
  return (text.match(/\/_next\//g)||[]).length - (text.match(/TEST_TOKEN_123\/_next\//g)||[]).length;
}
function fetchP(port, urlPath, withIngress) {
  return new Promise((resolve, reject) => {
    const h = withIngress !== false ? {"x-ingress-path": INGRESS_PATH} : {};
    http.get({hostname:"127.0.0.1",port,path:urlPath,headers:h}, res => {
      const c=[]; res.on("data",d=>c.push(d));
      res.on("end",()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(c).toString()}));
    }).on("error",reject);
  });
}
async function run() {
  const MP=13001, PP=13000;
  const routes = {
    "/":{ct:"text/html; charset=utf-8",body:'<!DOCTYPE html><html><head><title>T</title></head><body><script src="/_next/static/chunks/main.js"></script><script>self.__next_f.push([1,"{\\"src\\":\\"/_next/static/chunks/rsc.js\\"}"])</script><a href="/settings">S</a></body></html>'},
    "/settings":{ct:"text/html; charset=utf-8",body:'<!DOCTYPE html><html><head></head><body><script src="/_next/static/chunks/s.js"></script><p>Checking</p></body></html>'},
    "/_next/static/chunks/turbopack-abc.js":{ct:"application/javascript",body:'let t="/_next/",r=new WeakMap'},
    "/_next/static/chunks/main.js":{ct:"application/javascript",body:'console.log("main")'},
    "/_next/static/chunks/page.js":{ct:"application/javascript",body:'import"/_next/static/chunks/v.js"'},
    "/_next/static/chunks/style.css":{ct:"text/css",body:'@font-face{src:url(/_next/static/media/f.woff2)}'},
    "/_next/static/media/f.woff2":{ct:"font/woff2",body:"BIN"},
    "/api/garmin/auth":{ct:"application/json",body:'{"connected":false}'},
    "/settings?_rsc=1":{ct:"text/x-component",body:'1:I["/_next/static/chunks/sc.js","default"]\n'},
    "/?_rsc=abc":{ct:"text/plain;charset=utf-8",body:'1:I["/_next/static/chunks/h.js","d"]\n2:{"href":"/settings"}\n'},
  };
  const mock = http.createServer((req,res)=>{
    const r=routes[req.url];
    if(r){res.writeHead(200,{"content-type":r.ct});res.end(r.body);}
    else{res.writeHead(404);res.end("NF");}
  });
  await new Promise(r=>mock.listen(MP,r));
  const {execFile}=require("child_process");
  const pp=path.join(__dirname,"../../garmincoach/rootfs/app/ingress-proxy.js");
  const proc=execFile("node",[pp],{env:{...process.env,NEXT_INTERNAL_PORT:String(MP),PORT:String(PP)}});
  await new Promise(r=>setTimeout(r,500));
  try {
    console.log("\n-- HTML --");
    const home=await fetchP(PP,"/");
    test("all /_next/ rewritten",()=>assert.strictEqual(countRawNext(home.body),0));
    test("script src prefixed",()=>assert(home.body.includes('src="'+INGRESS_PATH+'/_next/static/chunks/main.js"')));
    test("RSC inline rewritten",()=>assert(home.body.includes(INGRESS_PATH+'/_next/static/chunks/rsc.js')));
    test("nav href prefixed",()=>assert(home.body.includes('href="'+INGRESS_PATH+'/settings"')));
    test("meta tag injected",()=>assert(home.body.includes('<meta name="ingress-path"')));
    test("no double-prefix",()=>assert(!home.body.includes(INGRESS_PATH+INGRESS_PATH)));
    console.log("\n-- Turbopack JS --");
    const tb=await fetchP(PP,INGRESS_PATH+"/_next/static/chunks/turbopack-abc.js");
    test("base path rewritten",()=>assert(tb.body.includes('let t="'+INGRESS_PATH+'/_next/"')));
    test("all /_next/ rewritten",()=>assert.strictEqual(countRawNext(tb.body),0));
    console.log("\n-- Regular JS --");
    const pg=await fetchP(PP,INGRESS_PATH+"/_next/static/chunks/page.js");
    test("import rewritten",()=>assert(pg.body.includes('"'+INGRESS_PATH+'/_next/static/chunks/v.js"')));
    const mn=await fetchP(PP,INGRESS_PATH+"/_next/static/chunks/main.js");
    test("no /_next/ unchanged",()=>assert.strictEqual(mn.body,'console.log("main")'));
    console.log("\n-- CSS --");
    const css=await fetchP(PP,INGRESS_PATH+"/_next/static/chunks/style.css");
    test("font url rewritten",()=>assert(css.body.includes("url("+INGRESS_PATH+"/_next/static/media/f.woff2)")));
    console.log("\n-- Binary --");
    const ft=await fetchP(PP,INGRESS_PATH+"/_next/static/media/f.woff2");
    test("font passthrough",()=>assert.strictEqual(ft.body,"BIN"));
    console.log("\n-- API --");
    const api=await fetchP(PP,INGRESS_PATH+"/api/garmin/auth");
    test("JSON OK",()=>assert.strictEqual(JSON.parse(api.body).connected,false));
    console.log("\n-- RSC Flight --");
    const r1=await fetchP(PP,INGRESS_PATH+"/settings?_rsc=1");
    test("x-component rewritten",()=>assert(r1.body.includes(INGRESS_PATH+"/_next/static/chunks/sc.js")));
    test("x-component no raw",()=>assert.strictEqual(countRawNext(r1.body),0));
    const r2=await fetchP(PP,INGRESS_PATH+"/?_rsc=abc");
    test("text/plain rewritten",()=>assert(r2.body.includes(INGRESS_PATH+"/_next/static/chunks/h.js")));
    test("href not corrupted",()=>assert(r2.body.includes('"href":"/settings"')));
    console.log("\n-- No Header --");
    const raw=await fetchP(PP,"/",false);
    test("paths unchanged",()=>assert(raw.body.includes('src="/_next/static/chunks/main.js"')));
    test("no meta tag",()=>assert(!raw.body.includes("ingress-path")));
    console.log("\n-- Prefix Strip --");
    const via=await fetchP(PP,INGRESS_PATH+"/settings");
    test("loads via ingress",()=>assert.strictEqual(via.status,200));
  } finally {
    try{process.send&&process.send({type:"terminate",pid:proc.pid})}catch(e){}
    proc.ref && proc.unref();
    mock.close();
    setTimeout(()=>process.exit(failed>0?1:0),100);
  }
  console.log("\n-- "+passed+" passed, "+failed+" failed --\n");
}
run().catch(e=>{console.error(e);process.exit(1)});
