import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Home, CheckCircle2, FileText, LayoutGrid, MessageSquareText, Trash2, Plus, Search, Link2, Bell,
  ChevronRight, MoreVertical, Presentation, UploadCloud, FolderPlus, Cloud, Share2, Star, Play,
  Download, Undo2, Redo2, Type, Image as ImageIcon, Table2, Settings, MousePointer2, Hand, Square,
  StickyNote, PenTool, BarChart3, PieChart, ListChecks, Send, Paperclip, Mic, AtSign, RotateCcw,
  Folder, Clock3, CircleCheck, AlertTriangle, X, Filter, SlidersHorizontal, Rows3, Grid2X2, Check,
  Sparkles, Bot, Users, Target, Megaphone, CalendarDays, HelpCircle, Pencil, Minus, Maximize2
} from 'lucide-react';
import './style.css';
import zimoHero from '../图片资源/1.svg';
import zimoLogo from '../图片资源/2.svg';
import zimoPro from '../图片资源/3.svg';

type Page = 'home'|'tasks'|'docs'|'ppt'|'docEditor'|'canvas'|'templates'|'chat'|'trash';
type DocType = 'PPT'|'文档'|'画布'|'表格'|'对话';
const cx = (...v:(string|false|undefined)[])=>v.filter(Boolean).join(' ');

const nav = [
  {id:'home', label:'首页', icon:Home}, {id:'tasks', label:'我的任务', icon:CheckCircle2, badge:6},
  {id:'docs', label:'我的文档', icon:FileText}, {id:'templates', label:'模板中心', icon:LayoutGrid},
  {id:'chat', label:'对话记录', icon:MessageSquareText}, {id:'trash', label:'回收站', icon:Trash2}
] as const;
const docs = [
  {title:'Q2 产品规划汇报', type:'PPT' as DocType, tag:'PPT生成', owner:'张一一', location:'我的文档 / 产品部', created:'今天 15:23', visited:'今天 19:41', tab:'最近访问', favorite:true},
  {title:'市场调研分析报告', type:'文档' as DocType, tag:'AI生成', owner:'李润蕾', location:'我的文档 / 市场部', created:'今天 10:08', visited:'今天 18:36', tab:'最近访问', favorite:false},
  {title:'AI 办公助手方案讨论', type:'对话' as DocType, tag:'外部', owner:'钱靖', location:'与我共享 / 办公提效项目', created:'昨天 16:47', visited:'今天 17:22', tab:'与我共享', favorite:false},
  {title:'产品需求文档 PRD', type:'文档' as DocType, tag:'AI生成', owner:'张一一', location:'我的文档 / 产品部', created:'昨天 14:15', visited:'今天 16:05', tab:'归我所有', favorite:true},
  {title:'竞品分析纪要', type:'文档' as DocType, tag:'', owner:'李润蕾', location:'与我共享 / 竞品研究', created:'4月28日 11:20', visited:'今天 15:48', tab:'与我共享', favorite:false},
  {title:'项目复盘总结', type:'文档' as DocType, tag:'AI生成', owner:'钱靖', location:'我的共享 / 项目管理', created:'4月26日 19:16', visited:'今天 14:30', tab:'与我共享', favorite:false},
  {title:'Q2 产品规划汇报 - 自由画布', type:'画布' as DocType, tag:'AI生成', owner:'张一一', location:'我的文档 / 产品部', created:'今天 16:40', visited:'今天 19:08', tab:'归我所有', favorite:false},
  {title:'Q2 需求进度跟踪表', type:'表格' as DocType, tag:'', owner:'赵子墨', location:'我的文档 / 项目管理', created:'4月24日 17:30', visited:'今天 10:22', tab:'与我共享', favorite:true}
] as const;
const tasks = [
  ['Q2 产品规划汇报','产品研发部',2,'今天 10:24','继续处理','blue'], ['市场调研分析报告','单聊：李明',3,'今天 09:48','继续处理','blue'],
  ['客户反馈分析','销售周会群',3,'昨天 16:32','去确认','orange'], ['周会纪要整理','文档提炼生成',4,'昨天 11:15','查看结果','green'],
  ['竞品分析纪要','模板创建',1,'4月27日 18:09','继续处理','blue']
] as const;
type TemplateRowItem = [string,string,string,any,string];
const templateRows: TemplateRowItem[] = [
  ['会议纪要','智能整理会议内容，提炼关键结论与待办事项','最受欢迎',FileText,'blue'], ['周报模板','结构化周报模板，帮你高效汇报工作进展','高效汇报',CalendarDays,'green'],
  ['项目复盘','全面复盘项目过程，沉淀经验与改进点','复盘总结',PieChart,'purple'], ['产品需求文档（PRD）','专业 PRD 模板，涵盖需求分析与功能设计','产品必备',FileText,'blue'], ['市场分析报告','多维度市场分析，洞察趋势与机会','数据驱动',BarChart3,'orange']
];
const templateCategories = ['热门推荐','办公协作','市场营销','产品运营','个人成长'];
const templateCategoryMap: Record<string, TemplateRowItem[]> = {
  '热门推荐': templateRows,
  '办公协作': [
    ['会议纪要','智能整理会议内容，提炼关键结论与待办事项','1.2k 人使用',FileText,'blue'],
    ['周报模板','结构化周报模板，帮你高效汇报工作进展','987 人使用',CalendarDays,'green'],
    ['项目复盘','全面复盘项目过程，沉淀经验与改进点','756 人使用',PieChart,'purple'],
    ['产品需求文档（PRD）','专业 PRD 模板，涵盖需求分析与功能设计','1.1k 人使用',FileText,'blue']
  ],
  '市场营销': [
    ['市场分析报告','多维度市场分析，洞察趋势与机会','1.5k 人使用',BarChart3,'orange'],
    ['用户调研报告','用户调研模板，收集洞察与建议','684 人使用',MessageSquareText,'green'],
    ['内容创作大纲','结构化内容大纲，提升创作效率与质量','921 人使用',FileText,'orange'],
    ['社交媒体运营计划','制定社媒运营策略，规划内容与发布计划','743 人使用',Target,'purple']
  ],
  '产品运营': [
    ['团队任务分配表','清晰分配任务，明确责任人与时间节点','1.2k 人使用',Users,'green'],
    ['工作计划表','制定详细工作计划，跟进进度与完成情况','987 人使用',ListChecks,'orange'],
    ['问题跟踪表','记录问题与解决方案，跟进处理进度','756 人使用',HelpCircle,'red']
  ],
  '个人成长': [
    ['决策记录表','记录关键决策过程与结果，便于追溯','632 人使用',FileText,'blue'],
    ['OKR 目标管理','设定目标与关键结果，驱动团队达成目标','1.1k 人使用',Target,'purple']
  ]
};

function App(){
  const [page,setPage]=useState<Page>('home');
  const [toast,setToast]=useState('');
  const [query,setQuery]=useState('');
  const [taskStep,setTaskStep]=useState(2);
  const [taskTab,setTaskTab]=useState('全部');
  const [docTab,setDocTab]=useState('最近访问');
  const [selectedChat,setSelectedChat]=useState(0);
  const [messages,setMessages]=useState(['下午好！我是子默，有什么可以帮你处理的？']);
  const [assistantNotes,setAssistantNotes]=useState<string[]>([]);
  const showToast=(t:string)=>{setToast(t); setTimeout(()=>setToast(''),1800)};
  const openDoc=(type:DocType)=> type==='PPT'?setPage('ppt'):type==='画布'?setPage('canvas'):type==='对话'?setPage('chat'):setPage('docEditor');
  return <div className="app-shell">
    <Sidebar page={page} setPage={setPage}/>
    <main className={cx('main', ['ppt','docEditor','canvas','chat'].includes(page)&&'main-editor')}>
      <Topbar page={page} query={query} setQuery={setQuery} showToast={showToast}/>
      {page==='home'&&<HomePage setPage={setPage} showToast={showToast} taskStep={taskStep} setTaskStep={setTaskStep}/>} 
      {page==='tasks'&&<TasksPage query={query} taskTab={taskTab} setTaskTab={setTaskTab} taskStep={taskStep} setTaskStep={setTaskStep} showToast={showToast} openDoc={openDoc}/>} 
      {page==='docs'&&<DocsPage query={query} docTab={docTab} setDocTab={setDocTab} openDoc={openDoc} showToast={showToast}/>} 
      {page==='ppt'&&<PptEditor assistantNotes={assistantNotes} setAssistantNotes={setAssistantNotes}/>} 
      {page==='docEditor'&&<DocEditor assistantNotes={assistantNotes} setAssistantNotes={setAssistantNotes}/>} 
      {page==='canvas'&&<CanvasEditor assistantNotes={assistantNotes} setAssistantNotes={setAssistantNotes}/>} 
      {page==='templates'&&<TemplatesPage query={query} showToast={showToast} openDoc={openDoc}/>} 
      {page==='chat'&&<ChatPage query={query} selectedChat={selectedChat} setSelectedChat={setSelectedChat} openDoc={openDoc}/>}
      {page==='trash'&&<TrashPage showToast={showToast}/>} 
    </main>
    {toast&&<div className="toast">{toast}</div>}
  </div>
}
function Sidebar({page,setPage}:{page:Page,setPage:(p:Page)=>void}){return <aside className="sidebar">
  <div className="brand"><img src={zimoLogo}/><div><strong>子默</strong><span> Zimo</span></div></div>
  <button className="new-btn" onClick={()=>setPage('chat')}><Plus size={20}/>新建</button>
  <nav className="nav-list">{nav.map(n=>{const I=n.icon;return <button key={n.id} className={cx('nav-item',page===n.id&&'active')} onClick={()=>setPage(n.id as Page)}><I size={21}/><span>{n.label}</span>{(n as any).badge&&<em>{(n as any).badge}</em>}</button>})}</nav>
  {page==='docs'&&<div className="recent-open"><div><b>最近打开</b><a>更多 <ChevronRight size={14}/></a></div>{docs.slice(0,5).map(d=><p key={d.title}><FileText size={16}/>{d.title.replace(' - 自由画布','')}</p>)}</div>}
  <div className="upgrade-card"><img src={zimoPro}/><div><b>升级子默 Pro</b><p>解锁更多 AI 能力</p><button>立即升级</button></div><ChevronRight size={18}/></div>
  <div className="user-box"><div className="user-avatar">张</div><b>张一一</b><ChevronRight size={14} className="down"/><div className="mini-bell"><Bell size={22}/><i>3</i></div></div>
</aside>}
function Topbar({page,query,setQuery,showToast}:{page:Page,query:string,setQuery:(v:string)=>void,showToast:(v:string)=>void}){const ph=page==='templates'?'搜索模板，例如：周报、会议纪要、项目复盘':page==='docs'?'搜索文档、内容或关键词（⌘+K）':page==='chat'?'搜索对话内容、任务、文档或模板':'搜索文档、任务、对话或模板';return <header className="topbar"><div className="search"><Search size={21}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder={ph}/><kbd>⌘ K</kbd></div><div className="top-actions"><button onClick={()=>showToast('已打开"接入更多对话"的模拟弹窗')}><Link2 size={19}/>接入更多对话</button><div className="bell"><Bell size={25}/><i/></div>{['docs','templates','chat'].includes(page)&&<div className="top-avatar">张</div>}</div></header>}

function HomePage({setPage,showToast,taskStep,setTaskStep}:any){const [text,setText]=useState(''); const chips=['整理群聊讨论','生成会议纪要','生成汇报文档','生成 PPT','分析对话待办']; return <>
  <section className="hero"><div className="hero-copy"><h1>下午好，张一一</h1><p>会接话 · 能推进 · 有温度</p></div><HeroMascot/></section>
  <div className="composer"><textarea value={text} onChange={e=>setText(e.target.value)} placeholder="把想法说给子默，例如：整理群聊并生成汇报"/><div className="composer-tools"><div><Paperclip size={21}/><Mic size={21}/></div><div><button className="voice"><BarChart3 size={19}/></button><button className="send" onClick={()=>{showToast(text?`已创建任务：${text}`:'请输入你的想法'); setText('')}}><Send size={21}/></button></div></div></div>
  <div className="chips">{chips.map(c=><button key={c} onClick={()=>setText(c)}><FileText size={18}/>{c}</button>)}</div>
  <div className="dashboard-grid"><CurrentTask step={taskStep} onNext={()=>setTaskStep(Math.min(4,taskStep+1))}/><RecentTasks/></div>
  <section className="card quick-start"><h3>快速开始</h3><div className="quick-grid">{chips.concat('更多模板').map((c,i)=><button className="quick-card" key={c} onClick={()=>i===5?setPage('templates'):showToast(`已选择：${c}`)}><IconBadge tone={['purple','green','blue','purple','orange','blue'][i]} icon={[MessageSquareText,FileText,FileText,Presentation,ListChecks,LayoutGrid][i]}/><b>{c}</b><p>{['提炼要点，生成汇报','智能记录，高效纪要','结构清晰，内容完整','一键生成，精美呈现','提取待办，跟进进度','浏览全部模板中心'][i]}</p><ChevronRight size={15}/></button>)}</div></section>
</>}
function HeroMascot(){return <><div className="orbit"><span/><i>✦</i><b>✧</b></div><img className="hero-zimo" src={zimoHero}/></>}
function CurrentTask({step,onNext}:{step:number,onNext:()=>void}){return <section className="card current-task"><div className="card-head"><b>当前任务</b><MoreVertical size={20}/></div><h2>Q2 产品规划汇报 <span><Presentation size={14}/>生成 PPT</span></h2><Progress step={step}/><div className="task-footer"><p>预计完成时间：今天 18:00</p><button onClick={onNext}>{step>=4?'查看结果':'继续处理'}</button></div></section>}
function RecentTasks(){return <section className="card recent-task"><div className="card-head"><b>最近任务</b><a>查看全部</a></div>{[['Q2 产品规划汇报','生成 PPT · 进行中','10:24','purple'],['市场分析报告','文档整理 · 已完成','昨天','blue'],['周会纪要 0428','生成文档 · 已完成','4月28日','green'],['客户反馈分析','对话分析 · 已完成','4月27日','orange']].map(r=><div className="task-row" key={r[0]}><IconBadge tone={r[3]} icon={FileText}/><div><b>{r[0]}</b><p>{r[1]}</p></div><time>{r[2]}</time></div>)}</section>}
function Progress({step}:{step:number}){const labels=['对话提取','文档整理','生成 PPT','优化完成'];return <div className="progress-wrap">{labels.map((l,i)=>{const n=i+1;return <div className="progress-item" key={l}>{i>0&&<span className={cx('line',n<=step&&'line-active')}/>}<span className={cx('dot',n<step&&'done',n===step&&'current')}>{n<step?<Check size={16}/>:n}</span><b className={n===step?'blue':''}>{l}</b><small>{n<step?'已完成':n===step?'进行中':'待开始'}</small></div>})}</div>}
function IconBadge({tone,icon:Icon}:{tone:string,icon:any}){return <span className={cx('icon-badge','tone-'+tone)}><Icon size={22}/></span>}

function TasksPage({query,taskTab,setTaskTab,taskStep,setTaskStep,showToast,openDoc}:any){const tabs=['全部','进行中','待我确认','已完成']; const filtered = tasks.filter(t=>{const text=`${t[0]} ${t[1]}`.toLowerCase(); if(query && !text.includes(query.toLowerCase())) return false; if(taskTab==='进行中') return t[2] < 4; if(taskTab==='待我确认') return t[4] === '去确认'; if(taskTab==='已完成') return t[4] === '查看结果'; return true;}); return <div className="page-content"><PageTitle title="我的任务" desc="查看由我发起、由子默生成并持续推进的任务进度" blue/><div className="stats-row">{[['全部任务',24,FileText,'blue'],['进行中',8,RotateCcw,'blue'],['待我确认',5,FileText,'orange'],['已完成',11,CheckCircle2,'green']].map(s=><StatCard key={s[0] as string} label={s[0]} value={s[1]} icon={s[2]} tone={s[3]}/>)}</div><div className="content-grid"><section className="card table-card task-table"><Tabs tabs={tabs} active={taskTab} setActive={setTaskTab}/><table><thead><tr><th>任务名称</th><th>来源</th><th>当前阶段</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{filtered.map(t=><tr key={t[0]}><td><b>{t[0]}</b></td><td>{t[1]}</td><td><MiniProgress step={t[2]}/></td><td>{t[3]}</td><td><button className={cx('link-action',t[5])} onClick={()=> t[4]==='查看结果'?openDoc('文档') : t[4]==='去确认'?showToast('已确认任务结果') : setTaskStep(Math.min(4,taskStep+1))}>{t[4]}</button><MoreVertical size={18}/></td></tr>)}</tbody></table><Pager/></section><aside className="right-stack"><TodoCard/><ActivityCard/></aside></div></div>}
function StatCard({label,value,icon,tone}:any){return <div className="stat-card card"><IconBadge tone={tone} icon={icon}/><div><p>{label}</p><b>{value}</b></div></div>}
function MiniProgress({step}:{step:number}){return <div className="mini-progress">{[1,2,3,4].map(n=><React.Fragment key={n}><span className={cx(n<=step?'on':'',step===3&&n<=3?'orange':'',step===4?'green':'')}>{n}</span>{n<4&&<i/>}</React.Fragment>)}<small>对话提取　文档整理　生成 PPT　优化完成</small></div>}
function TodoCard(){return <section className="card side-card"><div className="card-head"><b>今日待办</b><a>查看全部</a></div>{[['Q2 产品规划汇报','文档整理中','10:24','purple'],['市场调研分析报告','生成 PPT','09:48','blue'],['客户反馈分析','待确认','昨天 16:32','orange']].map(x=><div className="side-list" key={x[0]}><IconBadge tone={x[3]} icon={FileText}/><div><b>{x[0]}</b><p className={x[3]}>{x[1]}</p></div><time>{x[2]}</time></div>)}</section>}
function ActivityCard(){return <section className="card side-card activity"><div className="card-head"><b>最近动态</b><a>查看全部</a></div>{['子默已将《Q2 产品规划汇报》推进至文档整理阶段','子默已将《市场调研分析报告》推进至生成 PPT 阶段','子默等待你确认《客户反馈分析》的摘要内容','子默已完成《周会纪要整理》并生成最终结果'].map((a,i)=><p key={a}><i className={['blue','blue','orange','green'][i]}/>{a}<time>{['10:24','09:48','昨天 16:32','昨天 11:15'][i]}</time></p>)}</section>}

function DocsPage({query,docTab,setDocTab,openDoc,showToast}:any){const filtered=docs.filter(d=>{const text=`${d.title} ${d.location} ${d.owner}`.toLowerCase(); if(query && !text.includes(query.toLowerCase())) return false; if(docTab==='最近访问') return true; if(docTab==='归我所有') return d.owner==='张一一'; if(docTab==='与我共享') return d.owner!=='张一一'; if(docTab==='收藏') return d.favorite; return true;}); return <div className="page-content"><section className="doc-hero"><div><PageTitle title="我的文档" desc="集中管理 AI 生成内容与协作文档，支持持续编辑与沉淀"/></div><img src={zimoHero}/></section><div className="doc-actions"><ActionCard icon={FolderPlus} title="新建" desc="创建文档、表格、思维导图等" onClick={()=>showToast('已打开新建菜单')}/><ActionCard icon={UploadCloud} title="上传" desc="上传本地文件到云端" onClick={()=>showToast('请选择本地文件')}/><ActionCard icon={LayoutGrid} title="模板库" desc="选择模板快速新建" onClick={()=>openDoc('画布')}/></div><section className="card table-card doc-table"><div className="table-toolbar"><Tabs tabs={['最近访问','归我所有','与我共享','收藏']} active={docTab} setActive={setDocTab}/><div><button><Filter size={18}/>筛选</button><button><SlidersHorizontal size={18}/>显示设置</button><button className="selected"><Rows3 size={18}/></button><button><Grid2X2 size={18}/></button></div></div><table><thead><tr><th>标题</th><th>位置</th><th>所有者</th><th>创建时间</th><th>最近访问 ↓</th><th></th></tr></thead><tbody>{filtered.map(d=><tr key={d.title} onClick={()=>openDoc(d.type)}><td><DocIcon type={d.type}/><b>{d.title}</b>{d.tag&&<span className="tag">{d.tag}</span>}</td><td>{d.location}</td><td><span className="owner"><i>{d.owner[0]}</i>{d.owner}</span></td><td>{d.created}</td><td>{d.visited}</td><td><MoreVertical size={18}/></td></tr>)}</tbody></table></section></div>}
function PageTitle({title,desc,blue}:{title:string,desc:string,blue?:boolean}){return <div className="page-title"><h1>{title}</h1><p className={blue?'blue':''}>{desc}</p></div>}
function ActionCard({icon:Icon,title,desc,onClick}:any){return <button className="action-card card" onClick={onClick}><IconBadge tone="blue" icon={Icon}/><div><b>{title}</b><p>{desc}</p></div><ChevronRight size={22}/></button>}
function Tabs({tabs,active,setActive}:{tabs:string[],active:string,setActive:(v:string)=>void}){return <div className="tabs">{tabs.map(t=><button className={active===t?'active':''} onClick={()=>setActive(t)} key={t}>{t}</button>)}</div>}
function DocIcon({type}:{type:DocType}){const map:any={PPT:[Presentation,'orange'],文档:[FileText,'blue'],画布:[LayoutGrid,'purple'],表格:[Table2,'green'],对话:[MessageSquareText,'purple']}; const [I,t]=map[type]; return <IconBadge tone={t} icon={I}/>}
function Pager(){return <div className="pager"><ChevronRight className="left" size={18}/><button className="active">1</button><button>2</button><button>3</button><ChevronRight size={18}/></div>}

function TemplatesPage({query,showToast,openDoc}:any){const [activeCategory,setActiveCategory]=useState('热门推荐'); const categoryGroups=[['热门推荐'],['办公协作','会议沟通','周报日报','项目管理','团队协作'],['市场营销','产品运营','数据分析','个人成长'],['教育学习','创意写作']]; const items=templateCategoryMap[activeCategory]||templateRows; const filtered=items.filter(i=>!query||`${i[0]} ${i[1]}`.toLowerCase().includes(query.toLowerCase())); return <div className="page-content templates-page"><section className="template-hero"><PageTitle title="模板中心" desc="选择模板，子默将帮你快速生成高质量内容"/><img src={zimoHero}/></section><div className="template-layout"><aside className="category-card"><b>全部模板</b>{categoryGroups.flat().map((c,i)=><button key={c} className={activeCategory===c?'active':''} onClick={()=>setActiveCategory(c)}>{i===0?<Sparkles size={17}/>:null}{c}</button>)}<button className="apply" onClick={()=>showToast('已提交新模板申请')}><Plus size={18}/>申请新模板</button></aside><section className="template-main"><TemplateSection title={activeCategory==='热门推荐'?'热门推荐':'推荐模板'} items={filtered} openDoc={openDoc}/></section></div></div>}
function TemplateSection({title,items,openDoc}:any){return <div className="template-section"><div className="section-head"><h3>{title}</h3><a>查看全部 <ChevronRight size={14}/></a></div><div className="template-grid">{items.map((it:any)=><button className="template-card card" key={it[0]} onClick={()=>openDoc(it[0].includes('PPT')?'PPT':'文档')}><IconBadge tone={it[4]} icon={it[3]}/><b>{it[0]}</b><p>{it[1]}</p><span>{it[2]}</span></button>)}</div></div>}

function PptEditor({assistantNotes,setAssistantNotes}:any){const slides=['封面','背景','市场分析','方案建议','时间规划','总结'];return <EditorShell mode="ppt" title="Q2 产品规划汇报 演示稿" crumbs="我的文档 / Q2 产品规划汇报 / 演示稿" assistantNotes={assistantNotes} setAssistantNotes={setAssistantNotes}><div className="ppt-workspace"><aside className="slide-list">{slides.map((s,i)=><button className={i===0?'active':''} key={s}><span>{i+1}</span><div className="thumb"><b>{i===0?'Q2 产品规划汇报':''}</b></div><p>{s}</p></button>)}</aside><section className="ppt-canvas"><div className="ppt-toolbar"><Undo2/><Redo2/><span/><button>主题</button><button>布局</button><button>文本</button><button>图表</button><button>图片</button><button>批注</button><Settings/></div><div className="slide-stage"><small><img src={zimoLogo}/>子默 Zimo</small><time>2024 年 Q2</time><h1>Q2 产品规划汇报</h1><h2>聚焦增长 · 提升效率 · 创造价值</h2><div className="slide-points"><div><Target/>明确目标<p>聚焦核心场景<br/>提升用户价值</p></div><div><BarChart3/>驱动增长<p>优化产品能力<br/>扩大市场份额</p></div><div><Users/>创造价值<p>提升运营效率<br/>增强客户满意度</p></div></div><div className="chart-hero"><BarChart3 size={88}/></div><footer>汇报人：张一一　｜　产品部　｜　2024.04.28</footer></div><div className="notes-box">点击输入演讲备注...</div><div className="zoom-bar"><span>幻灯片 1 / 6</span><button><Minus/></button><b>67%</b><button><Plus/></button><button><Maximize2/></button></div></section></div></EditorShell>}
function DocEditor({assistantNotes,setAssistantNotes}:any){return <EditorShell mode="doc" title="Q2 产品规划汇报" crumbs="我的文档 / Q2 产品规划汇报" assistantNotes={assistantNotes} setAssistantNotes={setAssistantNotes}><div className="doc-editor"><div className="doc-toolbar"><Undo2/><Redo2/><select><option>正文</option></select><select><option>14</option></select><b>B</b><i>I</i><u>U</u><span>A</span><PenTool/><Rows3/><ListChecks/><Link2/><ImageIcon/><Table2/><MoreVertical/></div><div className="doc-layout"><aside className="outline"><b>大纲</b>{['背景与目标','市场分析','产品机会','关键策略','下一步计划'].map((x,i)=><button className={i===0?'active':''} key={x}>{x}</button>)}</aside><article className="doc-paper"><h2>一、背景与目标</h2><p>在宏观经济稳步复苏与行业竞争加剧的双重背景下，用户对产品的体验与效率提出了更高要求。我们需要通过产品创新与体验升级，巩固现有优势，开拓新的增长点，驱动业务持续增长。</p><b>本季度核心目标：</b><ul><li>提升核心产品的用户活跃度 15%以上；</li><li>完成 2 个重点功能迭代上线；</li><li>探索新的增长机会，验证 1 个创新方向；</li><li>提升客户满意度（NPS）至 50+。</li></ul><hr/><h2>二、市场分析</h2><p>整体市场保持增长，行业集中度进一步提升，头部产品在功能完善度与服务能力上持续领先。</p><ul><li>更看重产品的易用性与智能化；</li><li>对数据安全与隐私保护的关注度显著提升；</li><li>企业客户更偏向于一体化、可扩展的解决方案。</li></ul><hr/><h2>三、产品机会</h2><table><tbody><tr><th>机会点</th><th>描述</th><th>潜在价值</th><th>优先级</th></tr><tr><td>智能化体验升级</td><td>引入 AI 能力，提升使用效率与个性化体验</td><td>提升活跃与留存</td><td>高</td></tr></tbody></table></article></div></div></EditorShell>}
function CanvasEditor({assistantNotes,setAssistantNotes}:any){return <EditorShell mode="canvas" title="Q2 产品规划汇报 - 自由画布" crumbs="我的文档 / Q2 产品规划汇报 / 自由画布" assistantNotes={assistantNotes} setAssistantNotes={setAssistantNotes}><div className="canvas-editor"><div className="canvas-head"><span className="tag">AI 生成</span><span className="tag purple">自由画布</span><div><button><Play size={18}/></button><button><MessageSquareText size={18}/></button><button><Bell size={18}/></button><button><MoreVertical size={18}/></button></div></div><div className="canvas-tools">{[MousePointer2,Hand,Square,StickyNote,Type,PenTool,ImageIcon,Table2,LayoutGrid].map((I,i)=><button className={i===0?'active':''} key={i}><I size={20}/></button>)}</div><div className="whiteboard"><Sticky color="yellow" text="用户体验\n是核心竞争力"/><Sticky color="green" text="关注细分市场\n机会"/><Sticky color="purple" text="重点关注：\n1. 用户体验\n2. 数据驱动\n3. 持续迭代"/><CanvasNode className="center" title="Q2 产品规划汇报" tone="blue"/><CanvasNode className="n1" title="一、背景与目标" tone="blue"/><CanvasNode className="n2" title="二、市场分析" tone="purple"/><CanvasNode className="n3" title="三、产品机会" tone="green"/><CanvasNode className="n4" title="四、关键策略" tone="orange"/><CanvasNode className="n5" title="五、下一步计划" tone="blue"/><ChartCard/><PieCard/><FileChip title="竞品分析报告.pdf"/><FileChip title="产品路线图.png" image/></div><div className="canvas-bottom"><Undo2/><Redo2/><Play/><span/><Minus/><b>100%</b><Plus/><Maximize2/></div></div></EditorShell>}
function EditorShell({children,title,crumbs,mode,assistantNotes,setAssistantNotes}:any){return <div className="editor-page"><div className="editor-main"><div className="editor-breadcrumb"><span>{crumbs}</span><div><Cloud size={18}/>已保存　10:24 <span className="avatars"><i>张</i><i>钱</i><i>李</i><b>+2</b></span><button className="share"><Share2 size={18}/>分享</button>{mode==='ppt'&&<><button>演示</button><button>导出</button></>}<Star size={22}/><MoreVertical size={22}/></div></div><div className="editor-title"><h1>{title}</h1>{mode!=='canvas'&&<div><span className="tag">{mode==='ppt'?'PPT':'AI 生成'}</span>{mode==='doc'&&<span className="tag purple">PPT 生成</span>}</div>}</div>{children}</div><AssistantPanel notes={assistantNotes} setNotes={setAssistantNotes}/></div>}
function AssistantPanel({notes,setNotes}:any){const [text,setText]=useState(''); const actions:any[]=[['整理为 PPT','基于当前内容生成精美汇报 PPT',Presentation,'purple'],['优化结构','优化逻辑结构与段落层次',LayoutGrid,'blue'],['补充数据分析','补充行业数据与对比分析',BarChart3,'green'],['提炼结论','提炼关键结论与行动建议',MessageSquareText,'orange']]; return <aside className="assistant-panel"><div className="assistant-head"><b>子默助手</b><div><Star/><Clock3/><X/></div></div><img src={zimoHero}/><h3>会接话 · 能推进 · 有温度</h3><div className="assistant-tip"><CheckCircle2/> <p><b>文档草稿已生成</b><br/>内容结构清晰，论点完整。我可以继续帮你完善或扩展。</p></div>{actions.map(a=><button className="assistant-action" key={a[0]} onClick={()=>setNotes([...notes,`已触发：${a[0]}`])}><IconBadge tone={a[3]} icon={a[2]}/><span><b>{a[0]}</b><p>{a[1]}</p></span><ChevronRight/></button>)}{notes.map((n:string)=><p className="assistant-note" key={n}>{n}</p>)}<div className="assistant-input"><input value={text} onChange={e=>setText(e.target.value)} placeholder="继续告诉子默你的想法..."/><div><Paperclip/><AtSign/><button onClick={()=>{if(text){setNotes([...notes,`子默已收到：${text}`]); setText('')}}}><Send/></button></div></div><small>子默可能会出错，请核查重要信息。 <a>了解更多</a></small></aside>}
function Sticky({color,text}:any){return <div className={cx('sticky',color)}>{text.split('\n').map((x:string)=><p>{x}</p>)}<Star size={20}/></div>}
function CanvasNode({title,tone,className}:any){return <div className={cx('canvas-node',className,tone)}><b>{title}</b><p>• 智能化体验升级</p><p>• 引入 AI 能力提升效率</p><i>3</i></div>}
function ChartCard(){return <div className="chart-card"><b>用户增长趋势</b><svg viewBox="0 0 150 70"><polyline points="0,60 20,40 40,48 60,32 80,35 100,20 120,25 150,8" fill="none" stroke="#2165ff" strokeWidth="4"/></svg></div>}
function PieCard(){return <div className="pie-card"><b>流量来源占比</b><div/><p>自然搜索 42%</p><p>直接访问 28%</p></div>}
function FileChip({title,image}:any){return <div className={cx('file-chip',image&&'image')}><DocIcon type={image?'画布':'PPT'}/><b>{title}</b><p>{image?'PNG · 1.1MB':'PDF · 2.4MB'}</p></div>}

type ChatMsg={who:'bot'|'me',text:string,time:string,card?:{tone:string,icon:string,title:string,desc:string,action:string}};
const chatData:{name:string,sub:string,time:string,tone:string,messages:ChatMsg[]}[]=[
  {name:'Q2 产品规划汇报',sub:'已生成产品规划汇报文档',time:'10:24',tone:'purple',messages:[
    {who:'bot',text:'下午好！我是子默，有什么可以帮你处理的？',time:'10:18'},
    {who:'me',text:'帮我整理一份 Q2 产品规划汇报，包括背景、目标、市场分析、产品规划和运营策略。',time:'10:19'},
    {who:'bot',text:'好的，我将为你整理 Q2 产品规划汇报。为了更好地完成，请确认以下信息：<br/>1. 目标用户群体是否有特定定位？<br/>2. 是否已有初步的市场数据或竞品信息？<br/>3. 重点想突出产品的哪些方向？',time:'10:19'},
    {who:'me',text:'目标用户是中小企业团队，重点突出 AI 协同、效率提升和数据安全方向。',time:'10:20'},
    {who:'bot',text:'收到！我将基于这些信息为你生成完整的 Q2 产品规划汇报。',time:'10:21',card:{tone:'purple',icon:'FileText',title:'Q2 产品规划汇报',desc:'文档已生成 · 共 8,132 字',action:'查看文档'}},
    {who:'me',text:'帮我基于这份文档再生成一份 PPT，风格偏商务正式。',time:'10:22'},
    {who:'bot',text:'好的，已基于文档内容生成 PPT，共 6 页幻灯片，风格为商务正式。你可以让我调整某一页的内容或风格。',time:'10:23',card:{tone:'orange',icon:'Presentation',title:'Q2 产品规划汇报.pptx',desc:'PPT 已生成 · 共 6 页',action:'查看 PPT'}},
    {who:'me',text:'把第三页市场分析的图表换成饼图，并补充竞品对比数据。',time:'10:24'},
    {who:'bot',text:'已完成修改：<br/>• 第三页图表已替换为饼图<br/>• 新增竞品 A/B/C 的市场份额对比数据<br/>• 数据来源标注为 2024 Q1 行业报告<br/><br/>需要我继续调整其他页面吗？',time:'10:24'},
  ]},
  {name:'市场分析报告',sub:'已生成市场分析文档',time:'09:48',tone:'blue',messages:[
    {who:'bot',text:'你好！我是子默，今天有什么可以帮你的？',time:'09:30'},
    {who:'me',text:'我需要一份关于 AI 办公赛道的市场分析报告，重点关注国内市场。',time:'09:32'},
    {who:'bot',text:'好的，我来为你整理 AI 办公赛道的市场分析。请先确认几个问题：<br/>1. 分析周期是近一年还是近三年？<br/>2. 是否需要包含投融资数据？<br/>3. 目标读者是谁（内部决策/对外展示）？',time:'09:32'},
    {who:'me',text:'近一年的数据，需要投融资信息，目标读者是内部管理层。',time:'09:33'},
    {who:'bot',text:'收到！正在为你整理市场分析报告。',time:'09:35',card:{tone:'blue',icon:'FileText',title:'AI 办公赛道市场分析报告',desc:'文档已生成 · 共 12,450 字',action:'查看文档'}},
    {who:'me',text:'帮我提炼一下报告的核心结论。',time:'09:40'},
    {who:'bot',text:'核心结论如下：<br/><br/>📌 <b>市场规模</b>：2024 年国内 AI 办公市场规模约 280 亿元，同比增长 42%<br/>📌 <b>竞争格局</b>：头部 3 家厂商占据 55% 份额，但垂直赛道仍有窗口期<br/>📌 <b>融资趋势</b>：Q1 共 37 起融资事件，A 轮及以前占比 68%<br/>📌 <b>用户需求</b>：文档智能处理和会议纪要生成是最高频场景<br/>📌 <b>机会判断</b>：中小企业市场渗透率仅 12%，存在巨大增量空间',time:'09:41'},
    {who:'me',text:'把这些结论做成一页 PPT 摘要。',time:'09:47'},
    {who:'bot',text:'已生成 PPT 摘要页。',time:'09:48',card:{tone:'orange',icon:'Presentation',title:'市场分析核心结论.pptx',desc:'PPT 已生成 · 共 1 页',action:'查看 PPT'}},
  ]},
  {name:'周会纪要 0428',sub:'已提炼会议待办',time:'昨天',tone:'green',messages:[
    {who:'bot',text:'你好！可以把群聊记录或会议录音发给我，我来帮你整理纪要。',time:'16:00'},
    {who:'me',text:'帮我把今天下午产品周会的讨论整理成纪要，重点记录结论和待办。',time:'16:02'},
    {who:'bot',text:'好的，请提供会议内容（可以粘贴群聊记录、上传录音文件或直接描述）。',time:'16:02'},
    {who:'me',text:'会议主要讨论了三件事：1. Q2 规划的执行进展，张一一负责的产品模块已完成 60%；2. 客户反馈的批量导出问题，李润蕾承诺本周修复；3. 新功能"AI 摘要"的排期，计划 5 月中旬上线。',time:'16:05'},
    {who:'bot',text:'已整理完成！以下是会议纪要。',time:'16:07',card:{tone:'green',icon:'FileText',title:'周会纪要 0428',desc:'文档已生成 · 共 1,860 字',action:'查看文档'}},
    {who:'bot',text:'同时提炼了以下待办事项：<br/><br/>☐ 张一一：推进 Q2 产品模块至 100%，截止 5 月 15 日<br/>☐ 李润蕾：修复客户批量导出问题，截止本周五<br/>☐ 钱靖：确认"AI 摘要"功能的技术方案，截止 5 月 8 日<br/>☐ 全体：下周一同步进展',time:'16:07'},
    {who:'me',text:'把这些待办同步到任务列表里。',time:'16:08'},
    {who:'bot',text:'已创建 4 条待办任务，你可以在"我的任务"页面查看和跟进。',time:'16:08'},
  ]},
  {name:'客户反馈分析',sub:'待确认分析结论',time:'昨天',tone:'orange',messages:[
    {who:'bot',text:'下午好！需要我帮你分析什么数据？',time:'15:50'},
    {who:'me',text:'帮我把最近一周收集的客户反馈做一下分类分析，找出 Top 3 问题。',time:'15:52'},
    {who:'bot',text:'好的，请提供客户反馈数据，支持 Excel、CSV 或直接粘贴文本。',time:'15:52'},
    {who:'me',text:'数据已粘贴到附件里了。',time:'15:55'},
    {who:'bot',text:'已分析完成，共 247 条反馈。以下是分类结果：<br/><br/>🔴 <b>Top 1：导出功能问题</b>（68 条，占比 27.5%）<br/>　主要投诉：批量导出失败、格式不兼容<br/><br/>🟠 <b>Top 2：响应速度慢</b>（52 条，占比 21.1%）<br/>　主要场景：大文档加载、AI 生成等待<br/><br/>🟡 <b>Top 3：移动端体验</b>（41 条，占比 16.6%）<br/>　主要问题：排版错位、操作不便',time:'15:58',card:{tone:'orange',icon:'FileText',title:'客户反馈分析报告',desc:'文档已生成 · 共 3,240 字',action:'查看文档'}},
    {who:'me',text:'针对这三个问题，给出改进建议。',time:'16:00'},
    {who:'bot',text:'改进建议如下：<br/><br/>1️⃣ <b>导出功能</b>：优先修复批量导出 bug，新增 PDF/Word 双格式支持，预计 2 周完成<br/>2️⃣ <b>响应速度</b>：引入文档懒加载 + AI 流式输出，目标将等待时间降低 60%<br/>3️⃣ <b>移动端</b>：Q3 启动移动端专项优化，优先适配 iPad 和手机浏览器<br/><br/>请确认以上分析结论是否准确，我将据此生成正式报告。',time:'16:01'},
  ]},
  {name:'AI 办公趋势研究',sub:'研究中',time:'4月27日',tone:'purple',messages:[
    {who:'bot',text:'你好！有什么我可以帮你的？',time:'17:00'},
    {who:'me',text:'帮我调研一下 2024 年 AI 办公领域的主要趋势，整理成研究报告。',time:'17:02'},
    {who:'bot',text:'好的，我将从以下维度为你调研：<br/>1. 技术趋势（大模型、多模态、Agent）<br/>2. 产品形态（对话式、嵌入式、平台化）<br/>3. 市场格局（国内外对比）<br/>4. 用户需求演变<br/><br/>请确认是否需要调整？',time:'17:03'},
    {who:'me',text:'就这样，补充一下隐私合规方面的内容。',time:'17:04'},
    {who:'bot',text:'收到，已加入隐私合规维度。正在整理中...<br/><br/>我已完成初步调研，核心发现如下：<br/><br/>🔬 <b>技术趋势</b>：Agent 化是最大方向，从"工具调用"走向"自主决策"<br/>📱 <b>产品形态</b>：对话式 AI 办公渗透率最高，嵌入式 AI 增长最快<br/>🌍 <b>市场格局</b>：国内厂商在中文场景优势明显，但底层模型差距缩小<br/>🔒 <b>隐私合规</b>：欧盟 AI Act 推动全球合规升级，国内数据安全法持续完善<br/>📊 <b>用户需求</b>：从"效率工具"向"智能助手"转变',time:'17:20'},
    {who:'me',text:'生成完整报告文档。',time:'17:25'},
    {who:'bot',text:'已生成完整研究报告，报告包含 5 个章节、12 张数据图表和 3 个案例分析。',time:'17:30',card:{tone:'purple',icon:'FileText',title:'AI 办公趋势研究报告',desc:'文档已生成 · 共 15,680 字',action:'查看文档'}},
  ]},
  {name:'年度目标拆解',sub:'已生成拆解文档',time:'4月26日',tone:'blue',messages:[
    {who:'bot',text:'你好！需要我帮你做什么？',time:'14:00'},
    {who:'me',text:'帮我把团队年度目标拆解到季度和月度，目标包括：营收增长 50%、用户量翻倍、NPS 达到 60。',time:'14:02'},
    {who:'bot',text:'好的，我来帮你做目标拆解。请问：<br/>1. 团队规模和主要职能？<br/>2. 当前基线数据（营收、用户量、NPS）？<br/>3. 主要资源和预算限制？',time:'14:03'},
    {who:'me',text:'团队 30 人，产品+研发为主。当前 ARR 2000 万、用户 5 万、NPS 42。预算同比增长 30%。',time:'14:05'},
    {who:'bot',text:'目标拆解已完成：<br/><br/>📈 <b>营收增长 50%→3000 万</b><br/>　Q1：2200 万（+10%）→ 重点续约和增购<br/>　Q2：2500 万（+25%）→ 新客拓展加速<br/>　Q3：2800 万（+40%）→ 企业版上线<br/>　Q4：3000 万（+50%）→ 渠道规模化<br/><br/>👥 <b>用户量翻倍→10 万</b><br/>　Q1：6 万 → 内容营销+SEO<br/>　Q2：7.5 万 → 产品驱动增长<br/>　Q3：9 万 → 企业客户批量导入<br/>　Q4：10 万 → 口碑+推荐机制<br/><br/>💚 <b>NPS 达到 60</b><br/>　Q1：48 → 修复核心痛点<br/>　Q2：52 → 体验优化专项<br/>　Q3：56 → 客户成功体系建设<br/>　Q4：60 → 持续改进闭环',time:'14:10',card:{tone:'blue',icon:'FileText',title:'年度目标拆解方案',desc:'文档已生成 · 共 6,320 字',action:'查看文档'}},
    {who:'me',text:'把拆解结果生成一个跟踪表格。',time:'14:12'},
    {who:'bot',text:'已生成季度跟踪表。',time:'14:13',card:{tone:'green',icon:'Table2',title:'年度目标跟踪表',desc:'表格已生成 · 含季度里程碑',action:'查看表格'}},
  ]},
  {name:'竞品分析报告',sub:'已生成竞品对比',time:'4月25日',tone:'orange',messages:[
    {who:'bot',text:'你好！我可以帮你做竞品分析，请告诉我目标竞品和关注维度。',time:'10:00'},
    {who:'me',text:'帮我分析 Notion AI、飞书智能助手和钉钉 AI 助理这三款产品，关注功能对比和差异化策略。',time:'10:02'},
    {who:'bot',text:'好的，我将从以下维度对比分析：<br/>• 核心功能覆盖<br/>• AI 能力深度<br/>• 定价策略<br/>• 用户体验<br/>• 生态与集成<br/><br/>预计需要 2 分钟整理，请稍候...',time:'10:03'},
    {who:'bot',text:'分析完成！核心发现：<br/><br/>🏆 <b>Notion AI</b>：内容生成能力最强，但中文场景弱，价格偏高<br/>🏢 <b>飞书智能助手</b>：协作场景覆盖最全，但 AI 自主性不足<br/>💼 <b>钉钉 AI 助理</b>：企业渗透率高，但体验粗糙、功能分散<br/><br/>💡 <b>我们的差异化机会</b>：<br/>1. 中文 AI 能力 > Notion<br/>2. AI 主动推进能力 > 飞书<br/>3. 体验精致度 > 钉钉',time:'10:08',card:{tone:'orange',icon:'FileText',title:'竞品分析报告',desc:'文档已生成 · 共 9,850 字',action:'查看文档'}},
    {who:'me',text:'把功能对比做成表格形式。',time:'10:10'},
    {who:'bot',text:'已生成功能对比表格。',time:'10:11',card:{tone:'green',icon:'Table2',title:'竞品功能对比表',desc:'表格已生成 · 含 18 项功能对比',action:'查看表格'}},
  ]},
  {name:'项目复盘总结',sub:'已完成复盘',time:'4月24日',tone:'green',messages:[
    {who:'bot',text:'你好！我可以帮你做项目复盘，请告诉我项目名称和基本信息。',time:'18:00'},
    {who:'me',text:'帮我对"Q1 用户增长项目"做复盘，项目目标是 DAU 提升 30%，实际完成了 22%。',time:'18:02'},
    {who:'bot',text:'收到，我将按照复盘框架帮你分析：<br/>1. 目标与结果对比<br/>2. 做得好的地方<br/>3. 不足与原因<br/>4. 经验教训<br/>5. 下一步改进计划<br/><br/>请补充一些关键信息：主要采取了哪些增长手段？资源投入情况？',time:'18:03'},
    {who:'me',text:'主要做了三件事：内容营销（投入 2 人）、产品裂变功能（投入 3 人）、渠道合作（投入 1 人）。内容营销效果最好贡献了 60% 新增，裂变功能上线晚了一个月，渠道合作效果低于预期。',time:'18:06'},
    {who:'bot',text:'复盘总结如下：<br/><br/>📊 <b>目标达成</b>：DAU +22%，完成率 73%<br/><br/>✅ <b>做得好的</b>：<br/>• 内容营销策略精准，ROI 最高<br/>• 团队协作效率高，周会机制有效<br/><br/>⚠️ <b>不足之处</b>：<br/>• 裂变功能排期延迟 1 个月，错过春节流量高峰<br/>• 渠道合作前期调研不足，投入产出比低<br/>• 未设置阶段性 check-point<br/><br/>💡 <b>经验教训</b>：<br/>• 核心功能需预留 buffer time<br/>• 渠道合作需先做小规模验证<br/>• 建议双周复盘机制',time:'18:10',card:{tone:'green',icon:'FileText',title:'Q1 用户增长项目复盘',desc:'文档已生成 · 共 4,560 字',action:'查看文档'}},
  ]},
  {name:'内容创作思路',sub:'已整理创作大纲',time:'4月23日',tone:'purple',messages:[
    {who:'bot',text:'你好！需要我帮你创作什么内容？',time:'11:00'},
    {who:'me',text:'帮我想一下 AI 办公产品公众号的选题方向，目标读者是企业管理者。',time:'11:02'},
    {who:'bot',text:'好的，基于目标读者画像，我推荐以下选题方向：<br/><br/>📝 <b>方向一：效率提升类</b><br/>• "AI 如何让团队每周省出 8 小时"<br/>• "从会议纪要到执行方案：AI 办公实战"<br/><br/>📊 <b>方向二：趋势洞察类</b><br/>• "2024 AI 办公：从工具到助手的进化"<br/>• "企业管理者必看的 AI 办公趋势报告"<br/><br/>🎯 <b>方向三：场景案例类</b><br/>• "一家 50 人公司如何用 AI 提效 3 倍"<br/>• "产品经理的 AI 办公一天"',time:'11:05'},
    {who:'me',text:'帮我基于"AI 如何让团队每周省出 8 小时"这个选题，写一篇大纲。',time:'11:08'},
    {who:'bot',text:'已生成文章大纲：<br/><br/>📌 <b>AI 如何让团队每周省出 8 小时</b><br/><br/>一、开头：引入痛点——重复性工作占据团队 40% 时间<br/>二、AI 办公的 5 个高效场景<br/>　• 智能会议纪要（省 2h/周）<br/>　• 文档自动生成（省 1.5h/周）<br/>　• 数据分析报告（省 2h/周）<br/>　• 邮件智能回复（省 1h/周）<br/>　• 任务自动跟进（省 1.5h/周）<br/>三、落地建议：从最高频场景开始<br/>四、结尾：AI 不是替代，而是赋能',time:'11:12',card:{tone:'purple',icon:'FileText',title:'内容创作大纲',desc:'文档已生成 · 共 2,180 字',action:'查看文档'}},
  ]},
];

function ChatPage({query,selectedChat,setSelectedChat,openDoc}:any){const [input,setInput]=useState(''); const [chatMessages,setChatMessages]=useState<Record<number,ChatMsg[]>>({}); const filtered=chatData.filter(c=>!query||c.name.toLowerCase().includes(query.toLowerCase())); const activeIndex=Math.min(selectedChat,Math.max(0,filtered.length-1)); const current=filtered[activeIndex]??chatData[0]; const msgs=chatMessages[activeIndex]??current.messages; const sendMessage=()=>{const text=input.trim(); if(!text) return; const now=new Date(); const t=now.getHours()+':'+String(now.getMinutes()).padStart(2,'0'); const updated=[...msgs,{who:'me' as const,text,time:t},{who:'bot' as const,text:'收到，我会基于"'+text+'"继续处理。你也可以让我生成文档、PPT 或提炼待办。',time:t}]; setChatMessages({...chatMessages,[activeIndex]:updated}); setInput('')}; const iconMap:any={FileText,Presentation,Table2}; return <div className="chat-page card"><aside className="chat-list"><div><b>全部对话</b><Plus size={20}/></div>{filtered.map((c,i)=><button className={activeIndex===i?'active':''} onClick={()=>setSelectedChat(i)} key={c.name}><IconBadge tone={c.tone} icon={MessageSquareText}/><span><b>{c.name}</b><p>{c.sub}</p></span><time>{c.time}</time></button>)}</aside><section className="chat-main"><div className="chat-head"><h2>{current.name} <Pencil size={18}/></h2><div><button onClick={()=>openDoc('文档')}><FileText size={18}/>生成文档</button><button onClick={()=>openDoc('PPT')}><Presentation size={18}/>生成PPT</button><button><Share2 size={18}/>分享</button><MoreVertical/></div></div><div className="chat-body">{msgs.map((m,i)=><Bubble who={m.who} key={i} time={m.time} card={m.card} openDoc={openDoc} iconMap={iconMap}>{m.text}</Bubble>)}</div><div className="chat-input-wrap"><textarea value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage()}}} placeholder="给子默发送消息，继续推进当前对话" rows={1}/><div className="chat-input-tools"><Paperclip size={20}/><Mic size={20}/><button onClick={sendMessage}><Send size={20}/></button></div></div><div className="chat-chips">{['生成文档','生成 PPT','提炼待办','补充数据','优化结构'].map(x=><button onClick={()=>{const now=new Date(); const t=now.getHours()+':'+String(now.getMinutes()).padStart(2,'0'); setChatMessages({...chatMessages,[activeIndex]:[...msgs,{who:'me',text:x,time:t},{who:'bot',text:'好的，我会为你'+x+'，并把结果补充到当前对话里。',time:t}]})}} key={x}>{x}</button>)}</div></section></div>}
function Bubble({who,children,time,card,openDoc,iconMap}:any){return <div className={cx('bubble',who)}>{who==='bot'&&<img src={zimoLogo}/>}<div><span dangerouslySetInnerHTML={{__html:children}}/>{card&&<div className="result-card"><IconBadge tone={card.tone} icon={iconMap[card.icon]||FileText}/><b>{card.title}</b><p>{card.desc}</p><button onClick={()=>card.action.includes('PPT')?openDoc('PPT'):card.action.includes('表格')?openDoc('画布'):openDoc('文档')}>{card.action}</button></div>}<time>{time}</time></div></div>}

function TrashPage({showToast}:any){const [selected,setSelected]=useState<number[]>([]); const [trashTab,setTrashTab]=useState('全部'); const rows=[['Q2 产品规划汇报','PPT','我的文档 / 产品部','2025-04-28 10:24','27 天'],['市场调研分析报告','文档','我的文档 / 市场部','2025-05-20 14:32','5 天'],['周会纪要 0428','文档','我的文档 / 会议纪要','2025-05-24 09:15','1 天'],['AI 办公助手方案讨论','对话','对话记录','2025-05-25 16:48','2 天'],['客户反馈分析','PPT','我的文档 / 客户部','2025-05-18 11:03','12 天'],['项目复盘报告','文档','我的文档 / 项目部','2025-05-10 17:20','20 天'],['与市场部的需求对齐会','对话','对话记录','2025-05-12 10:05','22 天']]; const filtered=rows.filter(r=>trashTab==='全部' || r[1]===trashTab); return <div className="page-content"><PageTitle title="回收站" desc="集中管理已删除的文档、PPT、模板与对话记录，可恢复或彻底删除"/><div className="stats-row trash-stats"><StatCard label="全部项目" value={18} icon={Folder} tone="blue"/><StatCard label="7天内过期" value={6} icon={Clock3} tone="orange"/><StatCard label="已清空" value={0} icon={CircleCheck} tone="green"/></div><div className="content-grid trash-grid"><section className="card table-card"><div className="table-toolbar"><Tabs tabs={['全部','文档','PPT','模板','对话']} active={trashTab} setActive={setTrashTab}/><div><button onClick={()=>showToast('已批量恢复所选项目')}><RotateCcw size={18}/>批量恢复</button><button className="danger" onClick={()=>showToast('已清空回收站（模拟）')}><Trash2 size={18}/>清空回收站</button></div></div><table><thead><tr><th></th><th>名称</th><th>类型</th><th>原位置</th><th>删除时间</th><th>剩余天数</th><th>操作</th></tr></thead><tbody>{filtered.map((r,i)=><tr key={r[0]}><td><input type="checkbox" checked={selected.includes(i)} onChange={()=>setSelected(selected.includes(i)?selected.filter(x=>x!==i):[...selected,i])}/></td><td><DocIcon type={r[1] as DocType}/><b>{r[0]}</b></td><td><span className="tag">{r[1]}</span></td><td>{r[2]}</td><td>{r[3]}</td><td className={r[4].includes('1')||r[4].includes('5')?'orange':''}>{r[4]}</td><td><button className="link-action" onClick={()=>showToast(`已恢复：${r[0]}`)}>恢复</button><button className="delete" onClick={()=>showToast(`已彻底删除：${r[0]}`)}>彻底删除</button></td></tr>)}</tbody></table><div className="trash-footer">共 {filtered.length} 项 <Pager/></div></section><aside className="right-stack"><section className="card side-card"><div className="card-head"><b>即将过期</b><a>查看更多</a></div>{rows.slice(2,5).map((r,i)=><div className="side-list" key={r[0]}><DocIcon type={r[1] as DocType}/><b>{r[0]}</b><time>剩余 <span className="orange">{[1,2,5][i]} 天</span></time></div>)}</section><section className="card trash-info"><b><AlertTriangle size={18}/>回收站说明</b><p>删除内容将在 30 天后自动清除，恢复后将回到原位置。</p></section></aside></div></div>}

createRoot(document.getElementById('root')!).render(<App/>);
