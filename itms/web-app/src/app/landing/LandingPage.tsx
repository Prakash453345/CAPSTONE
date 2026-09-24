import { useEffect, useRef } from "react";
import { useTransitionStore } from "@/store/transitionStore";
import { preloadEarthTextures } from "@/components/transition/cinematicEarth";

/**
 * The marketing landing page at "/" — ported verbatim (markup, styles, and the
 * scroll-driven deck/network animations) from the original static prototype
 * at itms/web/index.html, now served from this app instead of a second
 * "web" build so there is exactly one frontend. Console links point at
 * "/console" instead of the old "live.html", and module images are served
 * from /public/landing/images. The CSS and animation script are kept as
 * plain strings (not hand-converted to JSX/React) because the scroll physics
 * and id-based DOM queries are load-bearing and easy to subtly break in a
 * line-by-line port.
 */

const LANDING_CSS = `
:root{
  --bg:#FAFAF9; --card:#FFFFFF; --ink:#14181A; --grey:#AFAFAB; --body:#5E6568;
  --line:#E7E5E1; --line2:#D9D6D1; --dark:#101416; --dark2:#191E21;
  --cy:#3FE0FF; --cy-d:#0A9AB0;
  --sans:'Plus Jakarta Sans',-apple-system,sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
  --gut:clamp(20px,4.6vw,56px); --max:1280px;
  --ease:cubic-bezier(.16,1,.3,1);
}
.landing-page *{box-sizing:border-box;margin:0;padding:0;}
.landing-page{scroll-behavior:smooth;}
.landing-page{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.6;
  -webkit-font-smoothing:antialiased;overflow-x:hidden;letter-spacing:-.011em;}
.landing-page a{color:inherit;text-decoration:none;}
.landing-page :focus-visible{outline:2px solid var(--ink);outline-offset:3px;border-radius:4px;}
.landing-page .wrap{max-width:var(--max);margin:0 auto;padding:0 var(--gut);}
.landing-page .mono{font-family:var(--mono);letter-spacing:0;}

/* ---------- type ---------- */
.landing-page h1,.landing-page h2,.landing-page h3,.landing-page h4{font-weight:600;letter-spacing:-.032em;line-height:1.02;}
.landing-page .h1{font-size:clamp(38px,5.6vw,80px);}
.landing-page .h2{font-size:clamp(30px,4.3vw,60px);}
.landing-page .dim{color:var(--grey);}
.landing-page p{color:var(--body);}
.landing-page .lede{font-size:clamp(15.5px,1.25vw,18px);line-height:1.6;color:var(--body);}
.landing-page .eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--grey);}

/* line-mask reveal */
.landing-page .lines .ln{display:block;overflow:hidden;padding-bottom:.14em;margin-bottom:-.14em;}
.landing-page .lines .ln>i{display:block;font-style:normal;transform:translateY(112%);
  transition:transform 1.05s var(--ease);}
.landing-page .lines.in .ln>i{transform:none;}
.landing-page .lines .ln:nth-child(2)>i{transition-delay:.09s;}
.landing-page .lines .ln:nth-child(3)>i{transition-delay:.18s;}

/* generic reveal */
.landing-page .rv{opacity:0;transform:translateY(26px);transition:opacity .9s var(--ease),transform .9s var(--ease);}
.landing-page .rv.in{opacity:1;transform:none;}
.landing-page .stg>*{opacity:0;transform:translateY(22px);transition:opacity .8s var(--ease),transform .8s var(--ease);}
.landing-page .stg.in>*{opacity:1;transform:none;}
.landing-page .stg.in>*:nth-child(1){transition-delay:.02s}.landing-page .stg.in>*:nth-child(2){transition-delay:.09s}
.landing-page .stg.in>*:nth-child(3){transition-delay:.16s}.landing-page .stg.in>*:nth-child(4){transition-delay:.23s}
.landing-page .stg.in>*:nth-child(5){transition-delay:.3s}.landing-page .stg.in>*:nth-child(6){transition-delay:.37s}
.landing-page .stg.in>*:nth-child(7){transition-delay:.44s}.landing-page .stg.in>*:nth-child(8){transition-delay:.51s}

/* ---------- floating nav ---------- */
.landing-page .navdock{position:fixed;top:16px;left:0;right:0;z-index:90;display:flex;justify-content:center;
  pointer-events:none;}
.landing-page .nav{pointer-events:auto;display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.82);
  backdrop-filter:blur(20px) saturate(1.6);border:1px solid var(--line);border-radius:999px;
  padding:7px 7px 7px 14px;box-shadow:0 4px 20px rgba(20,24,26,.06),0 1px 2px rgba(20,24,26,.05);
  transition:padding .6s var(--ease),gap .6s var(--ease),box-shadow .4s;}
.landing-page .nav .mark{display:flex;align-items:center;gap:9px;font-weight:700;font-size:15px;letter-spacing:-.02em;
  white-space:nowrap;padding-right:6px;}
.landing-page .nav .glyph{width:26px;height:26px;border-radius:50%;background:var(--ink);position:relative;flex:0 0 26px;}
.landing-page .nav .glyph::before{content:'';position:absolute;left:50%;top:6px;width:2.4px;height:9px;border-radius:2px;
  background:var(--cy);transform:translateX(-50%);}
.landing-page .nav .glyph::after{content:'';position:absolute;left:50%;bottom:6px;width:9px;height:2.4px;border-radius:2px;
  background:#5C6B70;transform:translateX(-50%);}
.landing-page .nav .lk{display:flex;align-items:center;gap:2px;overflow:hidden;max-width:520px;opacity:1;
  transition:max-width .6s var(--ease),opacity .35s var(--ease),margin .6s var(--ease);}
.landing-page .nav .lk a{padding:8px 13px;font-size:14px;color:var(--body);border-radius:999px;white-space:nowrap;
  transition:background .25s,color .25s;}
.landing-page .nav .lk a:hover{background:var(--bg);color:var(--ink);}
.landing-page .nav .cta{background:var(--ink);color:#fff;border-radius:999px;padding:9px 17px;font-size:14px;
  font-weight:500;white-space:nowrap;transition:transform .3s var(--ease),background .3s;}
.landing-page .nav .cta:hover{transform:translateY(-1px);background:#242A2D;}
.landing-page .nav .dots{display:none;width:34px;height:34px;border-radius:50%;background:var(--bg);border:0;
  cursor:pointer;align-items:center;justify-content:center;gap:3px;}
.landing-page .nav .dots i{width:3.4px;height:3.4px;border-radius:50%;background:var(--body);display:block;}
.landing-page .navdock.shrunk .nav{padding:7px 7px 7px 14px;}
.landing-page .navdock.shrunk .nav .lk{max-width:0;opacity:0;margin-left:-6px;}
.landing-page .navdock.shrunk .nav .cta{display:none;}
.landing-page .navdock.shrunk .nav .dots{display:flex;}
.landing-page .navdock.shrunk.open .nav .lk{max-width:520px;opacity:1;margin-left:0;}
.landing-page .navdock.shrunk.open .nav .cta{display:block;}

/* ---------- buttons ---------- */
.landing-page .btn{display:inline-flex;align-items:center;gap:9px;font-size:15px;font-weight:500;padding:13px 22px;
  border-radius:999px;background:var(--ink);color:#fff;border:1px solid var(--ink);white-space:nowrap;
  transition:transform .35s var(--ease),background .3s,box-shadow .35s;}
.landing-page .btn:hover{transform:translateY(-2px);background:#242A2D;box-shadow:0 10px 26px rgba(20,24,26,.16);}
.landing-page .btn.gh{background:transparent;color:var(--ink);border-color:var(--line2);}
.landing-page .btn.gh:hover{background:#fff;border-color:var(--ink);box-shadow:0 8px 22px rgba(20,24,26,.07);}
.landing-page .btn .av{width:26px;height:26px;border-radius:50%;background:#2B3336;margin:-6px 0 -6px -10px;
  display:flex;align-items:center;justify-content:center;flex:0 0 26px;}
.landing-page .btn .arw{transition:transform .3s var(--ease);}
.landing-page .btn:hover .arw{transform:translateX(4px);}
.landing-page .btn.sm{padding:10px 17px;font-size:14px;}

/* ---------- hero ---------- */
.landing-page .hero{padding:clamp(96px,11vw,150px) 0 clamp(40px,6vw,80px);position:relative;}
.landing-page .herogrid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.02fr);gap:clamp(24px,4vw,60px);
  align-items:center;}
.landing-page .badge{display:inline-flex;align-items:center;gap:8px;background:var(--card);border:1px solid var(--line);
  border-radius:999px;padding:6px 14px 6px 10px;font-size:13px;color:var(--body);font-weight:500;}
.landing-page .badge .live{width:7px;height:7px;border-radius:50%;background:#37B26A;box-shadow:0 0 0 0 rgba(55,178,106,.5);
  animation:landing-ping 2.4s ease-out infinite;}
@keyframes landing-ping{70%{box-shadow:0 0 0 7px rgba(55,178,106,0)}100%{box-shadow:0 0 0 0 rgba(55,178,106,0)}}
.landing-page .hero h1{margin:24px 0 22px;max-width:12ch;}
.landing-page .hero .lede{max-width:46ch;}
.landing-page .herocta{display:flex;gap:11px;flex-wrap:wrap;margin-top:30px;}
.landing-page .proof{display:flex;align-items:center;gap:13px;margin-top:34px;}
.landing-page .pstack{display:flex;}
.landing-page .pstack i{width:34px;height:34px;border-radius:50%;background:var(--dark);border:2.5px solid var(--bg);
  margin-left:-11px;display:flex;align-items:center;justify-content:center;flex:0 0 34px;}
.landing-page .pstack i:first-child{margin-left:0;}
.landing-page .proof .txt{font-size:13.5px;color:var(--body);line-height:1.35;}
.landing-page .proof .txt b{display:block;color:var(--ink);font-weight:600;font-size:14px;}

/* ---------- hero deck ---------- */
.landing-page .deck{position:relative;height:clamp(340px,44vw,560px);perspective:1500px;perspective-origin:56% 42%;}
.landing-page .c3d{position:absolute;left:50%;top:50%;width:78%;aspect-ratio:1.46;border-radius:15px;
  overflow:hidden;background:var(--dark);border:1px solid rgba(255,255,255,.085);
  transform-style:preserve-3d;backface-visibility:hidden;will-change:transform,opacity;
  box-shadow:0 42px 84px -26px rgba(20,24,26,.55),0 12px 28px -8px rgba(20,24,26,.2);}
.landing-page .c3d.float{width:45%;aspect-ratio:1.04;
  box-shadow:0 30px 62px -18px rgba(20,24,26,.5),0 8px 18px -6px rgba(20,24,26,.18);}
.landing-page .c3d .bar{height:24px;background:#0B0F11;display:flex;align-items:center;gap:5px;padding:0 11px;
  border-bottom:1px solid rgba(255,255,255,.06);}
.landing-page .c3d .bar b{width:6px;height:6px;border-radius:50%;background:#2B3439;display:block;flex:0 0 6px;}
.landing-page .c3d .bar span{margin-left:9px;font-family:var(--mono);font-size:8.5px;color:#4E6068;letter-spacing:.05em;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.landing-page .c3d .pane{position:absolute;inset:24px 0 0;overflow:hidden;}
.landing-page .c3d .pane svg{display:block;width:100%;height:100%;}

/* mini console fragments */
.landing-page .mini{padding:11px 12px 13px;font-family:var(--mono);color:#8FA5AD;font-size:9px;}
.landing-page .mini .rowx{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid #1B2225;}
.landing-page .mini .rowx:last-child{border-bottom:0;}
.landing-page .mini .k{color:#5E7178;}
.landing-page .mini .v{color:#DCE7EA;}
.landing-page .mini .cy{color:var(--cy);}
.landing-page .mini h6{font-family:var(--sans);font-size:11.5px;color:#E7EFF1;font-weight:600;letter-spacing:-.01em;
  margin-bottom:7px;}
.landing-page .mini .lbl{font-size:8px;letter-spacing:.14em;color:#4E6068;text-transform:uppercase;margin-bottom:6px;}
.landing-page .mini .big{font-family:var(--sans);font-size:26px;font-weight:700;color:#fff;letter-spacing:-.03em;line-height:1;}
.landing-page .gr{display:flex;align-items:center;gap:8px;margin-bottom:7px;}
.landing-page .gr .lane{flex:1;height:10px;position:relative;}
.landing-page .gr .bar2{position:absolute;height:10px;border-radius:3px;}
.landing-page .gbar{height:9px;border-radius:2px;margin:4px 0;}

/* ---------- marquee ---------- */
.landing-page .marq{border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:22px 0;
  overflow:hidden;position:relative;background:var(--bg);}
.landing-page .marqin{display:flex;align-items:center;gap:0;}
.landing-page .marqlbl{flex:0 0 auto;padding:0 var(--gut);font-size:14.5px;color:var(--body);white-space:nowrap;}
.landing-page .marqlbl b{color:var(--ink);font-weight:600;}
.landing-page .marqwin{overflow:hidden;position:relative;flex:1;
  -webkit-mask-image:linear-gradient(90deg,transparent,#000 7%,#000 93%,transparent);
  mask-image:linear-gradient(90deg,transparent,#000 7%,#000 93%,transparent);}
.landing-page .marqtrack{display:flex;width:max-content;animation:landing-slide 40s linear infinite;}
@keyframes landing-slide{to{transform:translateX(-50%)}}
.landing-page .marqwin:hover .marqtrack{animation-play-state:paused;}
.landing-page .mq{display:flex;align-items:center;gap:9px;padding:0 26px;font-size:15px;font-weight:500;
  color:#9A9A95;white-space:nowrap;transition:color .3s;}
.landing-page .mq:hover{color:var(--ink);}
.landing-page .mq s{width:19px;height:19px;border-radius:5px;background:#E3E1DD;display:block;text-decoration:none;}

/* ---------- sections ---------- */
.landing-page section{padding:clamp(64px,8vw,128px) 0;}
.landing-page .shead{display:grid;grid-template-columns:1fr auto;gap:26px;align-items:end;
  margin-bottom:clamp(30px,4vw,52px);}
.landing-page .shead .sub{max-width:40ch;}

/* module cards */
.landing-page .mods{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.landing-page .mod{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:24px 24px 0;
  overflow:hidden;transition:box-shadow .5s var(--ease),border-color .4s;
  backface-visibility:hidden;-webkit-backface-visibility:hidden;}
.landing-page .mod:hover{box-shadow:0 26px 56px -20px rgba(20,24,26,.24);border-color:var(--line2);}
.landing-page .mod.is-stacked{box-shadow:0 40px 80px -26px rgba(20,24,26,.42),0 10px 24px -8px rgba(20,24,26,.16);}
.landing-page .mods.fold-armed .mod{will-change:transform;transform-origin:50% 50%;contain:paint;}
.landing-page .modvis{margin:-24px -24px 0;background:var(--dark);position:relative;
  overflow:hidden;border-radius:18px 18px 0 0;}
.landing-page .modvis img{display:block;width:100%;aspect-ratio:758/508;object-fit:cover;transition:transform .7s var(--ease);}
.landing-page .mod:hover .modvis img{transform:scale(1.04);}
.landing-page .viewpill{position:absolute;right:16px;bottom:16px;background:rgba(255,255,255,.94);color:var(--ink);
  font-size:13px;font-weight:600;padding:9px 16px;border-radius:999px;display:flex;align-items:center;gap:6px;
  white-space:nowrap;
  opacity:0;transform:translateY(8px);pointer-events:none;
  transition:opacity .35s var(--ease),transform .35s var(--ease);box-shadow:0 10px 24px rgba(20,24,26,.18);}
.landing-page .mod:hover .viewpill{opacity:1;transform:none;}
.landing-page .modfoot{display:flex;align-items:center;justify-content:space-between;padding:18px 0;gap:12px;}
.landing-page .modfoot .n{font-size:18px;font-weight:600;letter-spacing:-.015em;display:block;}
.landing-page .modfoot .sub{font-size:13px;color:var(--grey);display:block;margin-top:2px;}
.landing-page .modfoot .g{font-size:13.5px;color:var(--grey);display:flex;align-items:center;gap:6px;white-space:nowrap;}

/* ---------- statement ---------- */
.landing-page .stmt{text-align:center;max-width:24ch;margin:0 auto;font-size:clamp(24px,3.5vw,46px);
  font-weight:500;letter-spacing:-.032em;line-height:1.14;}
.landing-page .stmt b{font-weight:600;}
.landing-page .stmt .dim{color:var(--grey);font-weight:500;}
.landing-page .stmtby{display:flex;align-items:center;justify-content:center;gap:11px;margin-top:30px;}
.landing-page .stmtby .ic{width:38px;height:38px;border-radius:50%;background:var(--ink);display:flex;
  align-items:center;justify-content:center;}
.landing-page .stmtby .t{text-align:left;font-size:13.5px;color:var(--grey);line-height:1.35;}
.landing-page .stmtby .t b{display:block;color:var(--ink);font-weight:600;font-size:14px;}

/* ---------- capability list ---------- */
.landing-page .caplist{display:grid;grid-template-columns:1fr 1fr;gap:clamp(28px,5vw,80px);align-items:start;}
.landing-page .cl{display:flex;flex-direction:column;gap:2px;}
.landing-page .cl a,.landing-page .cl div.row{display:flex;align-items:center;gap:15px;padding:13px 0;border-bottom:1px solid var(--line);
  transition:padding-left .4s var(--ease);}
.landing-page .cl div.row:hover{padding-left:8px;}
.landing-page .cl .ic{width:42px;height:42px;border-radius:50%;background:var(--ink);flex:0 0 42px;
  display:flex;align-items:center;justify-content:center;transition:transform .45s var(--ease);}
.landing-page .cl div.row:hover .ic{transform:rotate(-12deg) scale(1.06);}
.landing-page .cl .nm{font-size:19px;font-weight:600;letter-spacing:-.025em;}
.landing-page .cl .ds{font-size:13.5px;color:var(--grey);margin-top:1px;}
.landing-page .chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px;}
.landing-page .chip{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:9px 13px;
  font-size:13px;color:var(--body);font-weight:500;transition:transform .35s var(--ease),box-shadow .35s;}
.landing-page .chip:hover{transform:translateY(-3px);box-shadow:0 8px 18px rgba(20,24,26,.08);}

/* ---------- flow ---------- */
.landing-page .flow{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;}
.landing-page .fs{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;
  transition:transform .5s var(--ease),box-shadow .5s var(--ease);}
.landing-page .fs:hover{transform:translateY(-5px);box-shadow:0 22px 46px -20px rgba(20,24,26,.2);}
.landing-page .fs .t{font-size:34px;font-weight:700;letter-spacing:-.04em;line-height:1;}
.landing-page .fs .t sub{font-family:var(--mono);font-size:12px;font-weight:400;color:var(--grey);vertical-align:baseline;
  margin-left:3px;letter-spacing:0;}
.landing-page .fs h4{font-size:17px;margin:12px 0 8px;}
.landing-page .fs p{font-size:13.6px;}
.landing-page .fs .ev{display:block;font-family:var(--mono);font-size:10px;color:var(--grey);margin-top:14px;
  padding-top:11px;border-top:1px solid var(--line);letter-spacing:.02em;}

/* ---------- dark metric band ---------- */
.landing-page .band{background:var(--dark);color:#fff;border-radius:26px;padding:clamp(32px,5vw,64px);
  position:relative;overflow:hidden;}
.landing-page .band .glow{position:absolute;right:-140px;top:-140px;width:460px;height:460px;border-radius:50%;
  background:radial-gradient(circle,rgba(63,224,255,.16),transparent 65%);pointer-events:none;}
.landing-page .band h2{color:#fff;position:relative;}
.landing-page .band .dim{color:#5B686D;}
.landing-page .band p{color:#9BAAB0;}
.landing-page .mets{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:#232A2D;margin-top:44px;
  border:1px solid #232A2D;border-radius:14px;overflow:hidden;position:relative;}
.landing-page .met{background:var(--dark);padding:24px 22px 26px;}
.landing-page .met b{display:block;font-size:clamp(30px,3.6vw,46px);font-weight:700;letter-spacing:-.04em;
  line-height:1;color:#fff;}
.landing-page .met span{display:block;font-size:13.4px;color:#93A3A9;margin-top:9px;}
.landing-page .met em{display:block;font-family:var(--mono);font-style:normal;font-size:9.5px;letter-spacing:.13em;
  text-transform:uppercase;color:#5B686D;margin-top:12px;}

/* ---------- phases ---------- */
.landing-page .phases{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.landing-page .ph{border:1px solid var(--line);border-radius:20px;padding:30px;background:var(--card);
  display:flex;flex-direction:column;}
.landing-page .ph.now{background:var(--dark);border-color:var(--dark);color:#fff;}
.landing-page .ph.now p{color:#9BAAB0;}
.landing-page .ph.now .fl li{color:#C3D0D4;border-color:#232A2D;}
.landing-page .ph.now .fl li::before{background:var(--cy);}
.landing-page .ph .tagx{align-self:flex-start;font-family:var(--mono);font-size:10px;letter-spacing:.13em;
  text-transform:uppercase;padding:5px 11px;border-radius:999px;background:rgba(63,224,255,.14);
  color:var(--cy);margin-bottom:18px;}
.landing-page .ph:not(.now) .tagx{background:var(--bg);color:var(--grey);}
.landing-page .ph h3{font-size:27px;margin-bottom:9px;}
.landing-page .ph.now h3{color:#fff;}
.landing-page .ph>p{font-size:14.4px;margin-bottom:22px;}
.landing-page .fl{list-style:none;margin-top:auto;}
.landing-page .fl li{font-size:14px;padding:10px 0 10px 22px;border-bottom:1px solid var(--line);position:relative;
  color:var(--body);}
.landing-page .fl li:last-child{border-bottom:0;}
.landing-page .fl li::before{content:'';position:absolute;left:0;top:18px;width:9px;height:1.6px;background:var(--ink);}
.landing-page .contract{margin-top:16px;border:1px dashed var(--line2);border-radius:16px;padding:20px 22px;
  font-size:14px;color:var(--body);line-height:1.75;background:var(--card);}
.landing-page .contract b{color:var(--ink);font-weight:600;}

/* ---------- faq ---------- */
.landing-page .faqgrid{display:grid;grid-template-columns:1.35fr .85fr;gap:clamp(20px,3vw,42px);align-items:start;}
.landing-page .fq{background:var(--card);border:1px solid var(--line);border-radius:15px;margin-bottom:10px;
  transition:box-shadow .4s,border-color .4s;}
.landing-page .fq.open{box-shadow:0 14px 34px -18px rgba(20,24,26,.22);border-color:var(--line2);}
.landing-page .fqb{width:100%;background:none;border:0;cursor:pointer;text-align:left;display:flex;gap:14px;
  align-items:center;padding:19px 20px;font-family:inherit;color:inherit;}
.landing-page .fqb .n{font-family:var(--mono);font-size:12px;color:var(--grey);flex:0 0 22px;}
.landing-page .fqb .q{flex:1;font-size:16.5px;font-weight:600;letter-spacing:-.022em;line-height:1.3;}
.landing-page .fqb .ic{flex:0 0 24px;height:24px;position:relative;transition:transform .5s var(--ease);}
.landing-page .fqb .ic::before,.landing-page .fqb .ic::after{content:'';position:absolute;background:var(--ink);left:50%;top:50%;
  transform:translate(-50%,-50%);border-radius:2px;}
.landing-page .fqb .ic::before{width:12px;height:1.7px;}
.landing-page .fqb .ic::after{width:1.7px;height:12px;transition:opacity .35s;}
.landing-page .fq.open .ic{transform:rotate(180deg);}
.landing-page .fq.open .ic::after{opacity:0;}
.landing-page .fqa{max-height:0;overflow:hidden;transition:max-height .55s var(--ease);}
.landing-page .fqa div{padding:0 54px 20px 56px;font-size:14.6px;color:var(--body);}
.landing-page .stickcard{position:sticky;top:100px;background:var(--card);border:1px solid var(--line);
  border-radius:20px;padding:26px;}
.landing-page .stickcard .ic{width:52px;height:52px;border-radius:50%;background:var(--ink);margin-bottom:18px;
  display:flex;align-items:center;justify-content:center;}
.landing-page .stickcard h3{font-size:23px;margin-bottom:10px;}
.landing-page .stickcard h3 .dim{display:block;}
.landing-page .stickcard p{font-size:14.2px;margin-bottom:20px;}

/* ---------- cta ---------- */
.landing-page .ctac{background:var(--dark);border-radius:26px;padding:clamp(34px,5.5vw,74px);position:relative;
  overflow:hidden;display:grid;grid-template-columns:1fr auto;gap:34px;align-items:end;}
.landing-page .ctac h2{color:#fff;position:relative;}
.landing-page .ctac .glow{position:absolute;left:-120px;bottom:-160px;width:480px;height:480px;border-radius:50%;
  background:radial-gradient(circle,rgba(63,224,255,.15),transparent 66%);}
.landing-page .ctac p{color:#9BAAB0;max-width:36ch;margin-top:16px;position:relative;}
.landing-page .ctac .btn{background:#fff;color:var(--ink);border-color:#fff;}
.landing-page .ctac .btn:hover{background:#EDECEA;}
.landing-page .ctac .btn.gh{background:transparent;color:#fff;border-color:#33393C;}
.landing-page .ctac .btn.gh:hover{background:#1B2124;}

/* ---------- footer ---------- */
.landing-page footer{background:var(--dark);color:#fff;padding:clamp(50px,6vw,90px) 0 26px;margin-top:clamp(64px,8vw,128px);}
.landing-page .fgrid{display:grid;grid-template-columns:1.7fr 1fr 1fr 1fr;gap:30px;padding:0 0 40px;}
.landing-page .fgrid h5{font-family:var(--mono);font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;
  color:#5B686D;margin-bottom:15px;font-weight:400;}
.landing-page .fgrid a,.landing-page .fgrid span{display:block;color:#9BAAB0;font-size:14.5px;padding:5px 0;transition:color .25s;}
.landing-page .fgrid a:hover{color:#fff;}
.landing-page .fgrid span{color:#5B686D;}
.landing-page .kin{font-size:clamp(26px,3.6vw,44px);font-weight:600;letter-spacing:-.035em;line-height:1.08;
  margin-bottom:16px;color:#fff;}
.landing-page .kin+p{color:#9BAAB0;}
.landing-page .rot{display:inline-block;height:1.08em;overflow:hidden;vertical-align:bottom;color:var(--cy);}
.landing-page .rot>span{display:block;animation:landing-roll 8.4s cubic-bezier(.72,0,.28,1) infinite;}
.landing-page .rot i{display:block;height:1.08em;line-height:1.08;font-style:normal;}
.landing-page .kin .rot{font-size:inherit;color:var(--cy);padding:0;display:inline-block;}
.landing-page .kin .rot>span{font-size:inherit;padding:0;}
@keyframes landing-roll{0%,22%{transform:none}33%,55%{transform:translateY(-1.08em)}
  66%,88%{transform:translateY(-2.16em)}100%{transform:translateY(-3.24em)}}
.landing-page .wm{display:flex;justify-content:space-between;border-top:1px solid #232A2D;padding-top:12px;
  font-size:clamp(58px,20vw,268px);font-weight:800;letter-spacing:-.05em;line-height:.78;
  color:#1B2124;user-select:none;overflow:hidden;}
.landing-page .fbot{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;padding-top:18px;
  font-family:var(--mono);font-size:11px;color:#5B686D;letter-spacing:.02em;}

/* ---------- floating widget ---------- */
.landing-page .dock{position:fixed;right:20px;bottom:20px;z-index:88;display:flex;align-items:center;gap:8px;
  background:rgba(255,255,255,.88);backdrop-filter:blur(18px) saturate(1.5);border:1px solid var(--line);
  border-radius:999px;padding:8px 8px 8px 16px;box-shadow:0 8px 30px rgba(20,24,26,.13);
  transform:translateY(120px);opacity:0;transition:transform .8s var(--ease),opacity .6s var(--ease);}
.landing-page .dock.on{transform:none;opacity:1;}
.landing-page .dock .t{font-size:13px;line-height:1.3;color:var(--grey);}
.landing-page .dock .t b{display:block;color:var(--ink);font-weight:600;font-size:13.5px;}
.landing-page .dock .ib{width:36px;height:36px;border-radius:50%;background:var(--ink);display:flex;
  align-items:center;justify-content:center;transition:transform .35s var(--ease),background .3s;}
.landing-page .dock .ib:hover{transform:translateY(-3px) rotate(-8deg);}
.landing-page .dock .ib.alt{background:var(--bg);border:1px solid var(--line);}

/* ---------- responsive ---------- */
@media(max-width:1040px){
  .landing-page .herogrid{grid-template-columns:1fr;}
  .landing-page .deck{height:clamp(285px,54vw,420px);margin-top:20px;}
  .landing-page .c3d{width:86%;}
  .landing-page .c3d.float{width:50%;}
  .landing-page .mods,.landing-page .phases,.landing-page .caplist{grid-template-columns:1fr;}
  .landing-page .flow{grid-template-columns:1fr 1fr;}
  .landing-page .faqgrid{grid-template-columns:1fr;}
  .landing-page .stickcard{position:static;}
  .landing-page .mets{grid-template-columns:1fr 1fr;}
  .landing-page .fgrid{grid-template-columns:1fr 1fr;}
}
@media(max-width:700px){
  .landing-page .nav .lk{max-width:0;opacity:0;margin-left:-6px;}
  .landing-page .nav .dots{display:flex;}
  .landing-page .navdock.open .nav .lk{max-width:60vw;opacity:1;margin-left:0;overflow-x:auto;}
  .landing-page .flow{grid-template-columns:1fr;}
  .landing-page .shead{grid-template-columns:1fr;}
  .landing-page .ctac{grid-template-columns:1fr;}
  .landing-page .fgrid{grid-template-columns:1fr;}
  .landing-page .fqa div{padding:0 20px 20px;}
  .landing-page .dock .t{display:none;}
  .landing-page .dock{padding:8px;}
}
@media(prefers-reduced-motion:reduce){
  .landing-page *{animation-duration:.01ms!important;transition-duration:.01ms!important;}
  .landing-page .rv,.landing-page .stg>*{opacity:1;transform:none;}
  .landing-page .lines .ln>i{transform:none;}
}
`;

const LANDING_BODY_HTML = `
<div class="navdock" id="navdock">
  <nav class="nav">
    <a class="mark" href="#top"><span class="glyph"></span>ITMS</a>
    <div class="lk">
      <a href="#modules">Platform</a>
      <a href="#flow">How it responds</a>
      <a href="#deploy">Rollout</a>
      <a href="#faq">FAQ</a>
    </div>
    <a class="cta" href="/console">Try the live demo</a>
    <button class="dots" id="dots" aria-label="Menu"><i></i><i></i><i></i></button>
  </nav>
</div>

<main id="top">
<section class="hero">
  <div class="wrap">
    <div class="herogrid">
      <div>
        <span class="badge rv"><i class="live"></i> Live pilot program · Vijayawada</span>
        <h1 class="h1 lines">
          <span class="ln"><i class="dim">An ambulance should</i></span>
          <span class="ln"><i class="dim">never meet</i></span>
          <span class="ln"><i>a red light.</i></span>
        </h1>
        <p class="lede rv">Our platform spots incidents automatically, confirms them with a person before
          anything moves, sends the nearest available emergency unit, and clears a path of green lights
          ahead of it — then hands control back to normal traffic the moment it's through.</p>
        <div class="herocta rv">
          <a class="btn" href="/console"><span class="av">
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><path d="M2 7h10M8 3l4 4-4 4"
              stroke="#3FE0FF" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </span>Try the live demo</a>
          <a class="btn gh" href="#modules">See how it works</a>
        </div>
        <div class="proof rv">
          <div class="pstack">
            <i><svg width="15" height="15" viewBox="0 0 16 16" fill="none"><rect x="5.5" y="1.5" width="5" height="13" rx="2.5" stroke="#8FA5AD" stroke-width="1.3"/><circle cx="8" cy="5" r="1.2" fill="#3FE0FF"/></svg></i>
            <i><svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M1.5 11h13M3 11V7l2.5-3h5L13 7v4" stroke="#8FA5AD" stroke-width="1.3" stroke-linejoin="round"/><circle cx="4.8" cy="12.6" r="1.3" stroke="#8FA5AD" stroke-width="1.3"/><circle cx="11.2" cy="12.6" r="1.3" stroke="#8FA5AD" stroke-width="1.3"/></svg></i>
            <i><svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M1.5 9c1.7-5 3.4-5 5 0s3.4 5 5 0 2.6-3.4 4 -1.7" stroke="#3FE0FF" stroke-width="1.3" stroke-linecap="round"/></svg></i>
          </div>
          <div class="txt"><b>20 intersections monitored live</b>
            Fully interactive — see it work for yourself, it's not a screenshot</div>
        </div>
      </div>

      <div class="deck" id="deck" aria-hidden="true"></div>
    </div>
  </div>
</section>

<div class="marq">
  <div class="marqin">
    <span class="marqlbl">Built for <b>reliability</b></span>
    <div class="marqwin"><div class="marqtrack" id="marq"></div></div>
  </div>
</div>

<section id="modules">
  <div class="wrap">
    <div class="shead">
      <h2 class="h2 lines"><span class="ln"><i class="dim">Four systems,</i></span>
        <span class="ln"><i>working as one.</i></span></h2>
      <p class="lede sub rv">Signals, cameras, routing and oversight all share the same live data, so the
        whole city responds together instead of as four separate systems.</p>
    </div>

    <div class="mods" id="mods">
      <article class="mod">
        <div class="modvis"><img src="/landing/images/module-signal.jpg" alt="Intelligent traffic operations illustration of an isometric junction with live adaptive signals" loading="lazy">
          <span class="viewpill">View module <svg width="11" height="11" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></span>
        </div>
        <div class="modfoot"><div><span class="n">Adaptive signal control</span><span class="sub">Responds to real traffic, in real time</span></div>
          <span class="g">01 <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span></div>
      </article>

      <article class="mod">
        <div class="modvis"><img src="/landing/images/module-anomaly.jpg" alt="AI-powered incident detection illustration of a CCTV camera flagging a collision on a highway" loading="lazy">
          <span class="viewpill">View module <svg width="11" height="11" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></span>
        </div>
        <div class="modfoot"><div><span class="n">Incident detection</span><span class="sub">Cameras and sensors, working together</span></div>
          <span class="g">02 <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span></div>
      </article>

      <article class="mod">
        <div class="modvis"><img src="/landing/images/module-corridor.jpg" alt="Green corridor management illustration of an ambulance following a signal-preempted route to a hospital" loading="lazy">
          <span class="viewpill">View module <svg width="11" height="11" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></span>
        </div>
        <div class="modfoot"><div><span class="n">Green corridor</span><span class="sub">A clear path, without disrupting the rest</span></div>
          <span class="g">03 <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span></div>
      </article>

      <article class="mod">
        <div class="modvis"><img src="/landing/images/module-command.jpg" alt="Network operations illustration of a signal network radiating from a central optimization hub" loading="lazy">
          <span class="viewpill">View module <svg width="11" height="11" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></span>
        </div>
        <div class="modfoot"><div><span class="n">Full audit trail</span><span class="sub">Every action recorded and traceable</span></div>
          <span class="g">04 <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><path d="M3 11L11 3M11 3H5M11 3v6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></span></div>
      </article>
    </div>
  </div>
</section>

<section style="padding-top:0">
  <div class="wrap">
    <div class="rv">
      <p class="stmt"><span class="dim">Technology should assist judgment, never replace it.</span> <b>So a
        camera can confirm a stalled vehicle on its own — but a person always confirms anything involving
        a human life.</b></p>
      <div class="stmtby">
        <span class="ic"><svg width="17" height="17" viewBox="0 0 18 18" fill="none"><path d="M9 2l6 3v4c0 3.4-2.4 6.2-6 7-3.6-.8-6-3.6-6-7V5l6-3z" stroke="#3FE0FF" stroke-width="1.4" stroke-linejoin="round"/></svg></span>
        <span class="t"><b>Human oversight, by design</b>Every dispatch decision is confirmed by a person</span>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="wrap">
    <div class="caplist">
      <div>
        <h2 class="h2 lines"><span class="ln"><i class="dim">Capabilities you</i></span>
          <span class="ln"><i>can rely on.</i></span></h2>
        <p class="lede rv" style="margin-top:20px;max-width:38ch">Not a feature list for its own sake. Each one
          exists to prevent a specific, real-world failure.</p>
        <p class="eyebrow rv" style="margin-top:34px">Highlights</p>
        <div class="chips stg" style="margin-top:12px">
          <span class="chip">Real-time monitoring</span><span class="chip">Automated detection</span><span class="chip">Human oversight</span>
          <span class="chip">Full audit trail</span><span class="chip">Built to scale</span><span class="chip">24/7 reliability</span>
        </div>
      </div>

      <div class="cl stg">
        <div class="row">
          <span class="ic"><svg width="18" height="18" viewBox="0 0 18 18" fill="none"><rect x="6" y="2" width="6" height="14" rx="3" stroke="#fff" stroke-width="1.4"/><circle cx="9" cy="6" r="1.3" fill="#3FE0FF"/></svg></span>
          <span><span class="nm">Smart signal timing</span><span class="ds">Adjusts to real traffic conditions</span></span>
        </div>
        <div class="row">
          <span class="ic"><svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M2 9s2.6-4.6 7-4.6S16 9 16 9s-2.6 4.6-7 4.6S2 9 2 9z" stroke="#fff" stroke-width="1.4"/><circle cx="9" cy="9" r="2" stroke="#3FE0FF" stroke-width="1.4"/></svg></span>
          <span><span class="nm">Incident detection</span><span class="ds">Cameras and sensors, cross-checked</span></span>
        </div>
        <div class="row">
          <span class="ic"><svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M2 12c2-6 4-6 6.5 0S13 12 16 7" stroke="#3FE0FF" stroke-width="1.4" stroke-linecap="round"/><path d="M2 4h14" stroke="#fff" stroke-width="1.4" stroke-dasharray="2 2.4" stroke-linecap="round"/></svg></span>
          <span><span class="nm">Green corridor</span><span class="ds">Clears a path without disrupting the rest</span></span>
        </div>
        <div class="row">
          <span class="ic"><svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M2 12h2.5l2.5-3 2.5 6 2.5-9 1.5 6H16" stroke="#fff" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
          <span><span class="nm">Smart routing</span><span class="ds">Based on real travel time, not just distance</span></span>
        </div>
        <div class="row">
          <span class="ic"><svg width="18" height="18" viewBox="0 0 18 18" fill="none"><rect x="2.5" y="2.5" width="13" height="13" rx="3" stroke="#fff" stroke-width="1.4"/><path d="M5.5 7h7M5.5 10h7M5.5 13h4" stroke="#3FE0FF" stroke-width="1.3" stroke-linecap="round"/></svg></span>
          <span><span class="nm">Full audit trail</span><span class="ds">Every decision recorded — approved or denied</span></span>
        </div>
        <div class="row">
          <span class="ic"><svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M9 2v6M9 2L6 5M9 2l3 3" stroke="#fff" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M3 10v4a1.5 1.5 0 001.5 1.5h9A1.5 1.5 0 0015 14v-4" stroke="#3FE0FF" stroke-width="1.4" stroke-linecap="round"/></svg></span>
          <span><span class="nm">Built-in resilience</span><span class="ds">Keeps working even if a part fails</span></span>
        </div>
        <div class="row">
          <span class="ic"><svg width="18" height="18" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="6.5" stroke="#fff" stroke-width="1.4"/><path d="M9 5.5v4l2.5 1.5" stroke="#3FE0FF" stroke-width="1.4" stroke-linecap="round"/></svg></span>
          <span><span class="nm">Complete history</span><span class="ds">Review exactly what happened, and why</span></span>
        </div>
      </div>
    </div>
  </div>
</section>

<section id="flow">
  <div class="wrap">
    <div class="shead">
      <h2 class="h2 lines"><span class="ln"><i class="dim">From incident to a</i></span>
        <span class="ln"><i>clear path, end to end.</i></span></h2>
      <p class="lede sub rv">Measured from the moment an incident occurs. Verification is deliberately
        human — and deliberately the slowest step.</p>
    </div>
    <div class="flow stg">
      <div class="fs"><div class="t">0<sub>s</sub></div><h4>Detect</h4>
        <p>A stalled vehicle or blockage is spotted automatically, using live camera feeds and traffic
          patterns together — before it's obvious to anyone watching.</p>
        </div>
      <div class="fs"><div class="t">+15<sub>s</sub></div><h4>Confirm</h4>
        <p>A trained operator reviews the evidence — the footage, the surrounding traffic data, the
          confidence score — and confirms it in seconds. Nothing dispatches without a person's say-so.</p>
        </div>
      <div class="fs"><div class="t">+16<sub>s</sub></div><h4>Dispatch &amp; route</h4>
        <p>The nearest available unit is found and given a path based on real, current travel time — not
          straight-line distance — with an estimated arrival at every intersection along the way.</p>
        </div>
      <div class="fs"><div class="t">+31<sub>s</sub></div><h4>Clear the way</h4>
        <p>Signals ahead of the unit turn green just before it arrives, then return to normal the moment
          it's through — handing the junction straight back to everyday traffic.</p>
        </div>
    </div>
  </div>
</section>

<section style="padding-top:0">
  <div class="wrap">
    <div class="band rv">
      <div class="glow"></div>
      <h2 class="h2"><span class="dim">Built for one city.</span><br>Ready for many.</h2>
      <p class="lede" style="max-width:52ch;margin-top:20px">Designed from the ground up to grow — from a
        single district to an entire city — without reworking how it works underneath.</p>
      <div class="mets stg">
        <div class="met"><b data-count="20">0</b><span>Intersections under live control</span><em>Today</em></div>
        <div class="met"><b data-count="1" data-suffix="s">0</b><span>Dashboard refresh rate</span><em>Real-time</em></div>
        <div class="met"><b data-count="500" data-prefix="&lt;" data-suffix="ms">0</b><span>Signal response time</span><em>Target</em></div>
        <div class="met"><b data-count="24" data-suffix="/7">0</b><span>Continuous monitoring</span><em>Always on</em></div>
      </div>
    </div>
  </div>
</section>

<section id="deploy" style="padding-top:0">
  <div class="wrap">
    <div class="shead">
      <h2 class="h2 lines"><span class="ln"><i class="dim">From pilot</i></span>
        <span class="ln"><i>to city-wide.</i></span></h2>
      <p class="lede sub rv">Start with a single district. Expand across a whole city without changing how
        the system behaves.</p>
    </div>
    <div class="phases stg">
      <div class="ph now">
        <span class="tagx">Live now</span>
        <h3>A working pilot</h3>
        <p>A fully interactive environment covering 20 real intersections. Every decision, confirmation and
          route the system makes is real — only the street traffic itself is simulated for now.</p>
        <ul class="fl">
          <li>Realistic, real-time traffic simulation</li>
          <li>Every core capability fully operational, end to end</li>
          <li>The same data pipeline planned for city-wide rollout</li>
          <li>Secure, role-based access control from day one</li>
          <li>Automated testing and monitoring built in from the start</li>
        </ul>
      </div>
      <div class="ph">
        <span class="tagx">Built for</span>
        <h3>City-wide rollout</h3>
        <p>The same platform, connected to real infrastructure — with nothing about how it makes decisions
          changed in the process.</p>
        <ul class="fl">
          <li>Connects directly to existing city cameras and sensors</li>
          <li>Scales across multiple districts independently</li>
          <li>Full historical data for analytics and ongoing improvement</li>
          <li>Enterprise-grade security and data isolation between departments</li>
          <li>Automatically scales processing power to match demand</li>
        </ul>
      </div>
    </div>
    <div class="contract rv">
      <b>What stays the same:</b> how incidents are verified · how emergencies are prioritized · how every
      decision is recorded and can be reviewed.<br>
      <b>What changes:</b> only the scale of the infrastructure underneath.
    </div>
  </div>
</section>

<section id="faq">
  <div class="wrap">
    <div class="shead">
      <h2 class="h2 lines"><span class="ln"><i>Your questions</i></span>
        <span class="ln"><i class="dim">answered.</i></span></h2>
    </div>
    <div class="faqgrid">
      <div class="rv" id="faqlist">
        <div class="fq open">
          <button class="fqb" aria-expanded="true"><span class="n">01</span>
            <span class="q">What happens if part of the system fails during rush hour?</span><span class="ic"></span></button>
          <div class="fqa"><div>The system is built to fail safely. If the smart signal control ever goes
            offline, intersections automatically fall back to reliable pre-set timing — traffic never stops
            moving because of it. The same principle applies everywhere: if a camera feed is lost, detection
            relies on other data it already has; if data delivery slows down, routine updates are the first
            thing deprioritized, never anything related to an active incident.</div></div>
        </div>
        <div class="fq">
          <button class="fqb" aria-expanded="false"><span class="n">02</span>
            <span class="q">Can an operator override a signal whenever they want?</span><span class="ic"></span></button>
          <div class="fqa"><div>No — and that's intentional. Every signal has a minimum time it must stay
            green before it can be changed, and an active emergency route always outranks a manual request.
            If a request is denied, the operator is told exactly why and when they can try again — it never
            just fails silently. Every request, approved or denied, is logged for accountability.</div></div>
        </div>
        <div class="fq">
          <button class="fqb" aria-expanded="false"><span class="n">03</span>
            <span class="q">Why test in a simulated environment first?</span><span class="ic"></span></button>
          <div class="fqa"><div>Because it lets us prove the system works before it ever touches real
            infrastructure. The simulation behaves like a live city feed, so we can stress-test it, train it
            and refine it safely — then connect it to real cameras and sensors with confidence, without
            changing anything about how the system itself makes decisions.</div></div>
        </div>
        <div class="fq">
          <button class="fqb" aria-expanded="false"><span class="n">04</span>
            <span class="q">How are two emergencies wanting the same junction resolved?</span><span class="ic"></span></button>
          <div class="fqa"><div>If the requests don't conflict, both are simply granted. If they do, priority
            goes first to the more serious emergency, then to whichever route is already underway, then to
            whichever vehicle is closer. The lower-priority vehicle is rerouted if a good alternative exists —
            otherwise it still gets a boost, just a shorter one, instead of a full corridor. There's also a
            limit on how many routes can be cleared at once, so the system never creates gridlock while trying
            to prevent it.</div></div>
        </div>
        <div class="fq">
          <button class="fqb" aria-expanded="false"><span class="n">05</span>
            <span class="q">What stops this from becoming a surveillance system?</span><span class="ic"></span></button>
          <div class="fqa"><div>A firm rule built into how it works: cameras can automatically confirm traffic
            problems — a stalled vehicle, debris, an obstruction — but anything involving a person always goes
            to a human for review before any action is taken. That does mean a slightly slower response on
            that class of event, and it's a trade-off we made deliberately, to protect people's privacy.</div></div>
        </div>
      </div>

      <aside class="stickcard rv">
        <span class="ic"><svg width="22" height="22" viewBox="0 0 22 22" fill="none"><path d="M3 6.5A2.5 2.5 0 015.5 4h11A2.5 2.5 0 0119 6.5v9a2.5 2.5 0 01-2.5 2.5h-11A2.5 2.5 0 013 15.5v-9z" stroke="#fff" stroke-width="1.5"/><path d="M3.6 6l7.4 5.4L18.4 6" stroke="#3FE0FF" stroke-width="1.5" stroke-linecap="round"/></svg></span>
        <h3><span class="dim">Still not sure?</span>See it for yourself.</h3>
        <p>Try the live demo — trigger an incident, watch it get verified and dispatched, and see traffic
          signals respond in real time.</p>
        <a class="btn" href="/console">Try the live demo <span class="arw">→</span></a>
      </aside>
    </div>
  </div>
</section>

<section id="cta" style="padding-top:0">
  <div class="wrap">
    <div class="ctac rv">
      <div class="glow"></div>
      <div>
        <h2 class="h2"><span class="dim">See it run</span><br>before you believe it.</h2>
        <p>Try the live dashboard yourself — smart signal control, incident verification, live routing and
          emergency clearance, all working together in real time.</p>
      </div>
      <div style="display:flex;gap:11px;flex-wrap:wrap;position:relative">
        <a class="btn" href="/console">Try the live demo <span class="arw">→</span></a>
        <a class="btn gh" href="#deploy">How it scales</a>
      </div>
    </div>
  </div>
</section>
</main>

<footer>
  <div class="wrap">
    <div class="fgrid">
      <div>
        <div class="kin">Let’s <span class="rot"><span><i>detect</i><i>dispatch</i><i>clear</i><i>detect</i></span></span><br>the road ahead.</div>
        <p style="font-size:14.5px;max-width:32ch">Intelligent Traffic Management &amp; Emergency Response
          Platform · piloted in Vijayawada.</p>
      </div>
      <div><h5>Platform</h5>
        <a href="#modules">Modules</a><a href="#flow">How it responds</a>
        <a href="#deploy">Rollout</a><a href="#faq">FAQ</a></div>
      <div><h5>Our commitments</h5>
        <span>Human oversight</span><span>Full audit trail</span>
        <span>Privacy by design</span><span>Built to scale</span></div>
      <div><h5>Access</h5>
        <a href="/console">Live demo</a><span>Citizen app — coming soon</span>
        <span>Field mobile app — coming soon</span></div>
    </div>
    <div class="wm" aria-hidden="true"><span>I</span><span>T</span><span>M</span><span>S</span></div>
    <div class="fbot">
      <span>© 2026 · Intelligent Traffic Management Platform</span>
      <span>Some figures reflect target performance at full-city scale</span>
    </div>
  </div>
</footer>

<div class="dock" id="dock">
  <span class="t"><b>Try it now</b>Live demo or details</span>
  <a class="ib" href="/console" aria-label="Open console"><svg width="16" height="16" viewBox="0 0 18 18" fill="none"><rect x="2" y="3" width="14" height="11" rx="2" stroke="#fff" stroke-width="1.4"/><path d="M5.6 7l2 2-2 2M9.4 11H12" stroke="#3FE0FF" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></a>
  <a class="ib alt" href="#deploy" aria-label="Architecture"><svg width="16" height="16" viewBox="0 0 18 18" fill="none"><path d="M9 2l6 3.2v7.6L9 16l-6-3.2V5.2L9 2z" stroke="#14181A" stroke-width="1.4" stroke-linejoin="round"/><path d="M9 8.4l6-3.2M9 8.4v7.4M9 8.4L3 5.2" stroke="#14181A" stroke-width="1.4" stroke-linejoin="round"/></svg></a>
</div>
`;

/** The two animation IIFEs from the original prototype's inline <script> tags,
 * run verbatim against the document once the markup above is in the DOM.
 * Guarded by window.__landingBooted so React StrictMode's double-invoked
 * effect (dev only) doesn't attach every scroll/resize listener twice. */
const LANDING_SCRIPT = `
if (!window.__landingBooted) {
window.__landingBooted = true;
(function(){
"use strict";
var RM = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
var $ = function(s,r){ return (r||document).querySelector(s); };
var $$ = function(s,r){ return Array.prototype.slice.call((r||document).querySelectorAll(s)); };

var dock = $('#navdock');
function nscroll(){ dock.classList.toggle('shrunk', window.scrollY > 90); }
nscroll(); window.addEventListener('scroll', nscroll, {passive:true});
$('#dots').addEventListener('click', function(){ dock.classList.toggle('open'); });

var fd = $('#dock');
window.addEventListener('scroll', function(){ fd.classList.toggle('on', window.scrollY > 620); }, {passive:true});

var stack = ['Real-time monitoring','Automated incident detection','Adaptive signal control',
  'Emergency vehicle routing','Live traffic mapping','Role-based access control',
  'Continuous system health checks','Full audit logging','Built to scale',
  'Open mapping data','Secure data pipelines','24/7 uptime monitoring'];
var mk = stack.map(function(s){ return '<span class="mq"><s></s>'+s+'</span>'; }).join('');
$('#marq').innerHTML = mk + mk;

var targets = $$('.rv, .stg, .lines');
if('IntersectionObserver' in window && !RM){
  var io = new IntersectionObserver(function(es){
    es.forEach(function(e){
      if(!e.isIntersecting) return;
      e.target.classList.add('in');
      if(e.target.querySelector('[data-count]') || e.target.hasAttribute('data-count')) countUp(e.target);
      io.unobserve(e.target);
    });
  },{rootMargin:'0px 0px -9% 0px', threshold:.08});
  targets.forEach(function(t){ io.observe(t); });
} else {
  targets.forEach(function(t){ t.classList.add('in'); });
  countUp(document);
}

function countUp(root){
  $$('[data-count]', root).forEach(function(el){
    var to = parseFloat(el.getAttribute('data-count'));
    var pre = el.getAttribute('data-prefix') || '';
    var suf = el.getAttribute('data-suffix') || '';
    var dur = 1300, t0 = performance.now();
    if(RM){ el.textContent = pre + to + suf; return; }
    (function tick(now){
      var p = Math.min(1,(now-t0)/dur), e = 1-Math.pow(1-p,3);
      var val = to < 10 ? (to*e).toFixed(to%1?1:0) : Math.round(to*e);
      el.textContent = pre + val + suf;
      if(p<1) requestAnimationFrame(tick);
    })(t0);
  });
}

$$('.fq').forEach(function(fq){
  var b = $('.fqb',fq), a = $('.fqa',fq);
  if(fq.classList.contains('open')) requestAnimationFrame(function(){ a.style.maxHeight = a.scrollHeight+'px'; });
  b.addEventListener('click', function(){
    var was = fq.classList.contains('open');
    $$('.fq').forEach(function(o){
      o.classList.remove('open'); $('.fqa',o).style.maxHeight = null;
      $('.fqb',o).setAttribute('aria-expanded','false');
    });
    if(!was){ fq.classList.add('open'); a.style.maxHeight = a.scrollHeight+'px';
      b.setAttribute('aria-expanded','true'); }
  });
});

var DECK = [
  {fx:-24, fy:-16, fz:-46, tx:-148, ty:-84, tz:-300, rz:-9.5, sc:.90, dep:.030, br:.56, dl:.00},
  {fx: 17, fy:-11, fz:-31, tx: 126, ty:-102, tz:-215, rz: 7.5, sc:.93, dep:.052, br:.68, dl:.08},
  {fx: 11, fy:  9, fz:-17, tx: 188, ty:  48, tz:-125, rz: 4.5, sc:.95, dep:.074, br:.83, dl:.16},
  {fx:  0, fy:  0, fz:  0, tx:   0, ty:   0, tz:   0, rz: 0.0, sc:1,   dep:.104, br:1,   dl:.24},
  {fx: 64, fy: 60, fz: 58, tx: 150, ty: 138, tz: 140, rz:-4.0, sc:1,   dep:.150, br:1,   dl:.34}
];
var deck = $('#deck');
var cards = deck ? $$('.c3d', deck) : [];
var scrollY0 = 0, sy = 0, entry = 0, appear = 0, entering = false, t0 = 0, tAppear = 0;

window.addEventListener('scroll', function(){ scrollY0 = window.scrollY; }, {passive:true});

function startUnfold(){
  entering = true; entry = 0; appear = 0;
  tAppear = performance.now(); t0 = tAppear + HOLD_MS;
}

if(deck){
  cards.forEach(function(c,i){ c.style.opacity = '0'; });
  if('IntersectionObserver' in window && !RM){
    var armed = true;
    new IntersectionObserver(function(es){
      es.forEach(function(e){
        if(e.isIntersecting){ if(armed){ armed = false; startUnfold(); } }
        else { armed = true; }
      });
    },{threshold:.2}).observe(deck);
  } else { entry = 1; }
}

var UNFOLD_MS = 1100, HOLD_MS = 180, LAST_DL = 0.34;
var ease = function(p){ return p < .5 ? 4*p*p*p : 1 - Math.pow(-2*p + 2, 3)/2; };
var unfoldEase = function(p){ return 1 - Math.pow(1 - p, 2.6); };

var deckTop = 0;
function measure(){ if(deck) deckTop = deck.getBoundingClientRect().top + window.scrollY; }
window.addEventListener('resize', measure); window.addEventListener('load', measure); measure();

function paintDeck(){
  if(!deck) return;
  var range = 780;
  var scrollT = Math.max(0, Math.min(1, (sy - Math.max(0, deckTop - 460)) / range));
  var unfold = Math.min(1, scrollT * 1.28);
  var u = unfoldEase(unfold);

  var rotY = -19 + scrollT*13;
  var rotX =   9 - scrollT*6;

  cards.forEach(function(c,i){
    var d = DECK[i] || DECK[0];
    var p = Math.max(0, Math.min(1, (entry - d.dl) / (1 - LAST_DL)));
    var e = RM ? 1 : ease(p);

    var x = (d.fx + (d.tx - d.fx) * u) * e;
    var y = (d.fy + (d.ty - d.fy) * u) * e - sy * d.dep + (1-e)*46;
    var z = (d.fz + (d.tz - d.fz) * u) * e;
    var rz = d.rz * u * e;
    var sc = d.sc * (0.93 + 0.07*e);

    c.style.opacity = appear.toFixed(3);
    c.style.filter = d.br < 1 ? 'brightness(' + (d.br + (1-d.br)*0.45*u).toFixed(3) + ')' : '';
    c.style.transform =
      'translate(-50%,-50%) translate3d(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px,' + z.toFixed(1) + 'px)' +
      ' rotateY(' + rotY.toFixed(2) + 'deg) rotateX(' + rotX.toFixed(2) + 'deg)' +
      ' rotateZ(' + rz.toFixed(2) + 'deg) scale(' + sc.toFixed(3) + ')';
  });
}

(function deckLoop(now){
  if(!deck || !cards.length) return;
  requestAnimationFrame(deckLoop);
  sy += (scrollY0 - sy) * (RM ? 1 : .09);
  if(entering){
    appear = Math.min(1, (now - tAppear) / 420);
    var p = Math.max(0, Math.min(1, (now - t0) / UNFOLD_MS));
    entry = p;
    if(p >= 1) entering = false;
  } else if(!('IntersectionObserver' in window) || RM){ entry = 1; appear = 1; }
  paintDeck();
})(performance.now());

if(!RM) $$('.btn').forEach(function(b){
  b.addEventListener('mouseenter', function(){ b.style.transition = 'transform .2s cubic-bezier(.16,1,.3,1)'; });
  b.addEventListener('mousemove', function(e){
    var r = b.getBoundingClientRect();
    var x = (e.clientX - r.left - r.width/2) / r.width;
    var y = (e.clientY - r.top - r.height/2) / r.height;
    b.style.transform = 'translate('+(x*7).toFixed(1)+'px,'+(y*5-2).toFixed(1)+'px)';
  });
  b.addEventListener('mouseleave', function(){ b.style.transform = ''; b.style.transition = ''; });
});

var NS='http://www.w3.org/2000/svg';
function E(n,a){ var e=document.createElementNS(NS,n); for(var k in a) e.setAttribute(k,a[k]); return e; }
var svg = document.getElementById('netstrip');
if(svg){
  var NC=5, NR=4, nodes=[], edges=[], adj=[];
  for(var r=0;r<NR;r++) for(var c=0;c<NC;c++)
    nodes.push({x:90+c*180, y:84+r*120, c:c, r:r, phase:(c+r)%2?'NS':'EW', t:Math.random()*8, pre:false});
  for(var i=0;i<nodes.length;i++) adj.push([]);
  function link(a,b,ori){
    var A=nodes[a],B=nodes[b];
    edges.push({a:a,b:b,ori:ori,len:Math.hypot(A.x-B.x,A.y-B.y)});
    adj[a].push({e:edges.length-1,to:b}); adj[b].push({e:edges.length-1,to:a});
  }
  for(var r1=0;r1<NR;r1++) for(var c1=0;c1<NC-1;c1++) link(r1*NC+c1, r1*NC+c1+1,'H');
  for(var c2=0;c2<NC;c2++) for(var r2=0;r2<NR-1;r2++) link(r2*NC+c2,(r2+1)*NC+c2,'V');

  var veh=[];
  for(var v=0;v<72;v++){
    var ei=Math.floor(Math.random()*edges.length);
    veh.push({e:ei,dir:Math.random()<.5?1:-1,u:Math.random(),sp:34+Math.random()*16,stop:false});
  }

  for(var gx=0; gx<=900; gx+=45) svg.appendChild(E('line',{x1:gx,y1:0,x2:gx,y2:520,stroke:'#141A1D','stroke-width':1}));
  for(var gy=0; gy<=520; gy+=45) svg.appendChild(E('line',{x1:0,y1:gy,x2:900,y2:gy,stroke:'#141A1D','stroke-width':1}));

  var eEl = edges.map(function(e){
    var A=nodes[e.a],B=nodes[e.b];
    var l=E('line',{x1:A.x,y1:A.y,x2:B.x,y2:B.y,stroke:'#2B3B42','stroke-width':6,'stroke-linecap':'round'});
    svg.appendChild(l); return l;
  });
  var corLine = E('polyline',{points:'',fill:'none',stroke:'#3FE0FF','stroke-width':3.4,
    'stroke-linecap':'round','stroke-dasharray':'11 7',opacity:'0'});
  svg.appendChild(corLine);
  var vEl = veh.map(function(){ var c=E('circle',{r:2.3,fill:'#93AAB4'}); svg.appendChild(c); return c; });
  var nEl = nodes.map(function(n){
    var g=E('g',{});
    var ring=E('rect',{x:n.x-15,y:n.y-15,width:30,height:30,rx:5,fill:'none',stroke:'#3FE0FF','stroke-width':1.6,opacity:'0'});
    var box=E('rect',{x:n.x-9.5,y:n.y-9.5,width:19,height:19,rx:3,fill:'#0B0F11',stroke:'#2E383C','stroke-width':1});
    var bar=E('rect',{x:n.x-1.5,y:n.y-6.5,width:3,height:13,rx:1.5,fill:'#57C97B'});
    g.appendChild(ring); g.appendChild(box); g.appendChild(bar); svg.appendChild(g);
    return {ring:ring,bar:bar};
  });
  var unit=E('g',{opacity:'0'});
  unit.appendChild(E('circle',{r:15,fill:'#3FE0FF',opacity:'.17'}));
  unit.appendChild(E('circle',{r:5.6,fill:'#3FE0FF',stroke:'#04222A','stroke-width':1.5}));
  svg.appendChild(unit);

  var cor=null, wait=2.5;
  function need(e){ return e.ori==='H' ? 'EW' : 'NS'; }
  function plan(){
    var start=Math.floor(Math.random()*nodes.length), path=[start], eids=[], cur=start, guard=0;
    while(path.length<5 && guard++<40){
      var outs=adj[cur].filter(function(o){ return path.indexOf(o.to)<0; });
      if(!outs.length) break;
      var p=outs[Math.floor(Math.random()*outs.length)];
      path.push(p.to); eids.push(p.e); cur=p.to;
    }
    return eids.length>=3 ? {path:path,eids:eids,leg:0,u:0} : null;
  }

  var last=performance.now();
  function frame(now){
    var dt=Math.min(.05,(now-last)/1000); last=now;
    var groups={};
    veh.forEach(function(vv,ix){ var k=vv.e+':'+(vv.dir>0?1:0); (groups[k]=groups[k]||[]).push(ix); });

    Object.keys(groups).forEach(function(k){
      var p=k.split(':'), ei=+p[0], fwd=p[1]==='1', e=edges[ei];
      var head=nodes[fwd?e.b:e.a];
      var green = head.phase===need(e);
      var g=groups[k].slice().sort(function(x,y){
        var a=fwd?veh[x].u:1-veh[x].u, b=fwd?veh[y].u:1-veh[y].u; return b-a;
      });
      var slot=0;
      g.forEach(function(ix){
        var vv=veh[ix], prog=fwd?vv.u:1-vv.u, line=.95-slot*.03;
        if(!green && prog>line-.02){
          vv.stop=true; slot++;
          var tgt=fwd?line:1-line; vv.u += (tgt-vv.u)*.2;
        } else { vv.stop=false; vv.u += (vv.dir*vv.sp*dt)/e.len; }
      });
    });

    veh.forEach(function(vv){
      if(vv.u>1||vv.u<0){
        var e=edges[vv.e], at=vv.u>1?e.b:e.a;
        var outs=adj[at].filter(function(o){return o.e!==vv.e;});
        var p=outs.length?outs[Math.floor(Math.random()*outs.length)]:adj[at][0];
        var ne=edges[p.e];
        vv.e=p.e; vv.dir= ne.a===at?1:-1; vv.u= ne.a===at?.006:.994;
      }
    });

    nodes.forEach(function(n){
      n.t+=dt;
      if(n.pre) return;
      if(n.t > 5.5 + (n.c*0.8+n.r*1.3)%4){ n.phase = n.phase==='NS'?'EW':'NS'; n.t=0; }
    });

    if(!cor){
      wait-=dt;
      if(wait<=0){
        cor=plan(); wait=11+Math.random()*4;
        if(cor){
          corLine.setAttribute('points', cor.path.map(function(p){return nodes[p].x+','+nodes[p].y;}).join(' '));
          corLine.setAttribute('opacity','.55'); unit.setAttribute('opacity','1');
        }
      }
    } else {
      var e=edges[cor.eids[cor.leg]];
      cor.u += (108*dt)/e.len;
      var ahead=cor.path[cor.leg+1];
      if(ahead!=null && cor.u>.34){ nodes[ahead].pre=true; nodes[ahead].phase=need(e); }
      if(cor.u>=1){
        var passed=cor.path[cor.leg+1];
        if(passed!=null){ nodes[passed].pre=false; nodes[passed].t=0; }
        cor.leg++; cor.u=0;
        if(cor.leg>=cor.eids.length){
          cor.path.forEach(function(p){ nodes[p].pre=false; });
          corLine.setAttribute('opacity','0'); unit.setAttribute('opacity','0'); cor=null;
        }
      }
      if(cor){
        var e2=edges[cor.eids[cor.leg]], A=nodes[e2.a], B=nodes[e2.b];
        var f = e2.a===cor.path[cor.leg], u = f?cor.u:1-cor.u;
        unit.setAttribute('transform','translate('+(A.x+(B.x-A.x)*u)+','+(A.y+(B.y-A.y)*u)+')');
      }
    }

    edges.forEach(function(e,ix){
      var g1=groups[ix+':1']||[], g0=groups[ix+':0']||[];
      var st=g1.concat(g0).filter(function(k){return veh[k].stop;}).length;
      var b=Math.min(1, st/4.5);
      eEl[ix].setAttribute('stroke', b>.7?'#C8384A': b>.42?'#E2703A': b>.16?'#E8B23A':'#2C6B49');
      eEl[ix].setAttribute('opacity', 0.4+b*0.52);
    });
    nodes.forEach(function(n,ix){
      var o=nEl[ix];
      o.ring.setAttribute('opacity', n.pre?'.95':'0');
      var col = n.pre?'#3FE0FF':'#57C97B';
      if(n.phase==='NS'){ o.bar.setAttribute('x',n.x-1.5); o.bar.setAttribute('y',n.y-6.5);
        o.bar.setAttribute('width',3); o.bar.setAttribute('height',13); }
      else { o.bar.setAttribute('x',n.x-6.5); o.bar.setAttribute('y',n.y-1.5);
        o.bar.setAttribute('width',13); o.bar.setAttribute('height',3); }
      o.bar.setAttribute('fill',col);
    });
    veh.forEach(function(vv,ix){
      var e=edges[vv.e],A=nodes[e.a],B=nodes[e.b];
      var u=Math.max(0,Math.min(1,vv.u)), L=Math.hypot(B.x-A.x,B.y-A.y);
      var off=vv.dir>0?3:-3, nx=(B.y-A.y)/L, ny=-(B.x-A.x)/L;
      vEl[ix].setAttribute('cx', A.x+(B.x-A.x)*u + nx*off);
      vEl[ix].setAttribute('cy', A.y+(B.y-A.y)*u + ny*off);
      vEl[ix].setAttribute('fill', vv.stop?'#5F7480':'#9FB6C0');
    });
    if(!RM) requestAnimationFrame(frame);
  }
  if(RM) frame(performance.now()); else requestAnimationFrame(frame);
}
})();

(function(){
  "use strict";
  var RM = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var grid  = document.getElementById('mods');
  var deck  = document.getElementById('deck');
  var mods  = document.getElementById('modules');
  if(!grid || !deck || !mods) return;

  var cards = Array.prototype.slice.call(grid.querySelectorAll('.mod'));
  if(!cards.length) return;

  var FOLD_X   = 62;
  var FOLD_Y   = -19;
  var FAN_X    = 15;
  var FAN_Y    = 11;
  var FAN_Z    = 2.6;
  var STAGGER  = 0.07;
  var ENABLED  = true;

  var slots = [], anchor = null, range = { start: 0, end: 1 };

  function measure(){
    ENABLED = window.innerWidth > 860 && !RM;
    cards.forEach(function(c){ c.style.transform = ''; });
    lastTf = [];

    var d = deck.getBoundingClientRect();
    anchor = {
      cx: d.left + d.width / 2,
      cy: d.top + window.scrollY + d.height / 2,
      w:  d.width
    };

    slots = cards.map(function(c){
      var r = c.getBoundingClientRect();
      return {
        cx: r.left + r.width / 2,
        cy: r.top + window.scrollY + r.height / 2,
        w:  r.width,
        h:  r.height
      };
    });

    var modsTop = mods.getBoundingClientRect().top + window.scrollY;
    range.start = 60;
    range.end   = Math.max(range.start + 320, modsTop - window.innerHeight * 0.34);

    grid.classList.toggle('fold-armed', ENABLED);
    if(!ENABLED) cards.forEach(function(c){
      c.style.transform=''; c.style.zIndex=''; c.style.pointerEvents='';
      c.classList.remove('is-stacked');
    });
  }

  var smoother = function(p){ return p*p*p*(p*(p*6 - 15) + 10); };
  var clamp01  = function(v){ return v < 0 ? 0 : v > 1 ? 1 : v; };

  var prog = 0, raf = 0, lastT = 0, lastTf = [];

  function paint(now){
    raf = requestAnimationFrame(paint);
    if(!ENABLED || !anchor) return;

    var dt = lastT ? Math.min(0.05, (now - lastT) / 1000) : 1/60;
    lastT = now;

    var sy = window.pageYOffset;

    var want = clamp01((sy - range.start) / (range.end - range.start));
    prog += (want - prog) * (1 - Math.pow(0.0012, dt));
    if(Math.abs(want - prog) < 0.0003) prog = want;

    var denom = 1 - STAGGER * (cards.length - 1);
    var mid   = (cards.length - 1) / 2;

    for(var i = 0; i < cards.length; i++){
      var c = cards[i], s = slots[i];
      var pi = clamp01((prog - i * STAGGER) / denom);

      var qRot = 1 - smoother(clamp01(pi / 0.58));
      var qPos = 1 - smoother(clamp01((pi - 0.30) / 0.70));

      if(qRot < 0.0008 && qPos < 0.0008){
        if(lastTf[i] !== ''){
          lastTf[i] = ''; c.style.transform = '';
          c.style.zIndex = ''; c.style.pointerEvents = '';
          c.classList.remove('is-stacked');
        }
        continue;
      }

      var scale = 1 + (((anchor.w * 0.74) / s.w) - 1) * qPos;
      var dx = (anchor.cx - s.cx + (i - mid) * FAN_X) * qPos;
      var dy = (anchor.cy - s.cy + sy + (i - mid) * FAN_Y) * qPos;

      var tf = 'translate3d(' + dx.toFixed(2) + 'px,' + dy.toFixed(2) + 'px,0)' +
        ' perspective(1400px)' +
        ' rotateX(' + (FOLD_X * qRot).toFixed(3) + 'deg)' +
        ' rotateY(' + (FOLD_Y * qRot).toFixed(3) + 'deg)' +
        ' rotateZ(' + ((i - mid) * FAN_Z * qRot).toFixed(3) + 'deg)' +
        ' scale(' + scale.toFixed(5) + ')';

      if(tf === lastTf[i]) continue;
      lastTf[i] = tf;
      c.style.transform = tf;

      var z = String(10 + (cards.length - i));
      if(c.style.zIndex !== z) c.style.zIndex = z;
      var pe = qPos > 0.12 ? 'none' : '';
      if(c.style.pointerEvents !== pe) c.style.pointerEvents = pe;
      var st = qPos > 0.04;
      if(c.classList.contains('is-stacked') !== st) c.classList.toggle('is-stacked', st);
    }
  }

  function boot(){ measure(); prog = clamp01((window.pageYOffset - range.start) / (range.end - range.start));
    if(!raf) raf = requestAnimationFrame(paint); }
  window.addEventListener('load', boot);
  window.addEventListener('resize', measure);
  if(document.readyState === 'complete') boot(); else setTimeout(boot, 350);

  window.__modFold = { measure: measure, cards: cards,
    progress: function(){ return clamp01((window.pageYOffset - range.start)/(range.end - range.start)); },
    range: function(){ return range; }, anchor: function(){ return anchor; } };
})();
}
`;

export function LandingPage() {
  const rootRef = useRef<HTMLDivElement>(null);
  const transitioning = useTransitionStore((s) => s.active);
  const startTransition = useTransitionStore((s) => s.start);

  useEffect(() => {
    document.title = "ITMS — Traffic that responds before you call it in";
    const run = new Function(LANDING_SCRIPT);
    run();
    // Warm the cinematic's Earth textures while the visitor reads, so the
    // dive starts the instant they click through.
    const warm = () => void preloadEarthTextures().catch(() => {});
    const idle = window.requestIdleCallback?.(warm, { timeout: 2500 });
    const fallback = idle === undefined ? window.setTimeout(warm, 1200) : undefined;
    return () => {
      if (idle !== undefined) window.cancelIdleCallback(idle);
      if (fallback !== undefined) window.clearTimeout(fallback);
      delete (window as typeof window & { __landingBooted?: boolean }).__landingBooted;
    };
  }, []);

  // Every link into the console ("Try the live demo" in the nav and hero,
  // the FAQ card, the footer dock, the final CTA) hands off to the
  // Globe-to-Console cinematic instead of a plain navigation — see
  // GlobeTransition, which owns the actual route change once it's underway.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onClick = (e: MouseEvent) => {
      const anchor = (e.target as HTMLElement).closest('a[href="/console"]');
      if (!anchor) return;
      e.preventDefault();
      startTransition(); // no-ops if a transition is already running
    };
    root.addEventListener("click", onClick);
    return () => root.removeEventListener("click", onClick);
  }, [startTransition]);

  // Fade + lock the landing page the instant a transition starts, so the
  // globe overlay is never covering content that's still fully interactive.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    root.style.transition = "opacity 480ms ease, filter 480ms ease";
    root.style.opacity = transitioning ? "0" : "1";
    root.style.filter = transitioning ? "blur(6px)" : "none";
    root.style.pointerEvents = transitioning ? "none" : "";
  }, [transitioning]);

  return (
    <div className="landing-page" ref={rootRef}>
      <style dangerouslySetInnerHTML={{ __html: LANDING_CSS }} />
      <div dangerouslySetInnerHTML={{ __html: LANDING_BODY_HTML }} />
    </div>
  );
}
