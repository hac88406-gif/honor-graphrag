# data/REVIEW.md — 数据审核清单（M1b 全量口径）

> 生成日期：2026-10-14　快照：`data/raw/20261014-230459`
> 本文件由 `scripts/build_review.py` 从 `data/graph/*.json` 与 `data/guides/*.md` 生成，所有 URL 均取自数据本身。

## 0. 审核指引（规格书 6.4「需求方审核要点」）

1. **抽查 5 条关系**：点开下表任一 `source` URL，确认官网页面上确实写着这条关系。
2. **方向核对**：`语义` 列写明了谁压制谁 / 谁与谁搭档；官网页面上「压制英雄」= 本英雄压制对方，「被压制英雄」= 对方压制本英雄。
3. **source / patch 完整性**：下表每条都有真实 URL 与 `2026-10`，无空缺。
4. **语料可读性**：见第 3 节，重点看 `llm_assisted` 的 C2 五篇有无模板腔。

## 1. 抓取规模与覆盖率

- 英雄 133 / 装备 115 / 铭文 93，全部抓取成功，`parse_errors` 为空。
- 三项关系区块覆盖率 133/133（每英雄恰 2/2/2 条）。详见 `data/fetch_report.md`。

## 2. 关系数据（M1b 全量口径）

- 关系总数：**798** 条（COUNTERS 532 / SYNERGIZES 266）
- 按页面区块：hr1 最佳搭档 266 / hr2 压制英雄 266 / hr3 被压制英雄 266
- 覆盖英雄：133 个全量入库（M1a 的「邻居英雄桩节点」随全量入库自然消失，桩节点数 = 0）

> 全量逐条（含每条 `source` URL）见 `data/graph/relations.json`；各英雄 COUNTERS 出度/入度与边界英雄清单见 `data/data_profile.md`。
> 下面保留 M1a 的 5 个演示英雄逐条清单（口径与 M1a 一致），便于需求方抽查方向与 URL。

### 2.1 演示英雄逐条清单

#### 2.1.1 貂蝉（id=141，30 条）

- 官方页：https://pvp.qq.com/web201605/herodetail/diaochan.shtml
- 分路：中路 / 对抗路　上手难度：60　patch：2026-10

| # | 关系 | 语义 | 该页区块 | 理由（官方原文） | source URL | patch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 貂蝉 → 廉颇（COUNTERS） | 貂蝉 压制 廉颇 | 被压制英雄 | 廉颇不能很容易控制到灵活的貂蝉 | https://pvp.qq.com/web201605/herodetail/lianpo.shtml | 2026-10 |
| 2 | 妲己 → 貂蝉（COUNTERS） | 妲己 压制 貂蝉 | 压制英雄 | 貂蝉：貂蝉比较怕硬控和集火秒杀，妲己的单体爆发比较高，可以在貂蝉秀起来之前一套231连招秒掉，注意在貂蝉交出2技能消失后在眩晕打出一套连招（中后期妲己经济碾压的情况下，即使貂蝉满血也可以秒掉）。 | https://pvp.qq.com/web201605/herodetail/daji.shtml | 2026-10 |
| 3 | 貂蝉 → 庄周（COUNTERS） | 貂蝉 压制 庄周 | 被压制英雄 | 由于灵活的貂蝉附带真实伤害，所以庄周在血量较低时需要注意貂蝉的追击 | https://pvp.qq.com/web201605/herodetail/zhuangzhou.shtml | 2026-10 |
| 4 | 貂蝉 → 刘禅（COUNTERS） | 貂蝉 压制 刘禅 | 被压制英雄 | 由于灵活的貂蝉附带真实伤害，使得刘禅的控制技能不容易控制到貂蝉 | https://pvp.qq.com/web201605/herodetail/liushan.shtml | 2026-10 |
| 5 | 高渐离 → 貂蝉（COUNTERS） | 高渐离 压制 貂蝉 | 压制英雄 | 貂蝉：高渐离有非常强的瞬间爆发输出能力，可以利用大招状态下的免伤效果提升自己的生存环境，配合被动伤害效果可以在短时间内成为一个恐怖的输出点。貂蝉更偏向于持续输出，利用位移和回复效果维持生存的同时打出高额的伤害。在对线或者团战的时候，貂蝉很难和高渐离对抗，经常都会被高渐离一套带走。 | https://pvp.qq.com/web201605/herodetail/gaojianli.shtml | 2026-10 |
| 6 | 貂蝉 → 钟无艳（COUNTERS） | 貂蝉 压制 钟无艳 | 被压制英雄 | 灵活的貂蝉会让钟无艳的技能很难打中她 | https://pvp.qq.com/web201605/herodetail/zhongwuyan.shtml | 2026-10 |
| 7 | 貂蝉 → 夏侯惇（COUNTERS） | 貂蝉 压制 夏侯惇 | 被压制英雄 | 貂蝉能在躲避技能同时很好的风筝夏侯惇 | https://pvp.qq.com/web201605/herodetail/xiahoudun.shtml | 2026-10 |
| 8 | 甄姬 → 貂蝉（COUNTERS） | 甄姬 压制 貂蝉 | 压制英雄 | 貂蝉：甄姬特点是团控，远程消耗，团战时甄姬能在安全的地方对交战区使用技能，二技能的弹射以及三技能的范围持续伤害，让甄姬极容易打出被动。一般貂蝉带净化，过了这两秒，甄姬在远处就能控住貂蝉，让我方输出击杀貂蝉。优势就在于，甄姬能远程消耗，而貂蝉必须近身打伤害。 | https://pvp.qq.com/web201605/herodetail/zhenji.shtml | 2026-10 |
| 9 | 貂蝉 → 甄姬（COUNTERS） | 貂蝉 压制 甄姬 | 被压制英雄 | 甄姬的技能并不能很好的限制貂蝉 | https://pvp.qq.com/web201605/herodetail/zhenji.shtml | 2026-10 |
| 10 | 貂蝉 → 典韦（COUNTERS） | 貂蝉 压制 典韦 | 被压制英雄 | 貂蝉的灵活和减速会使得典韦没有太多击杀办法 | https://pvp.qq.com/web201605/herodetail/dianwei.shtml | 2026-10 |
| 11 | 貂蝉 → 达摩（COUNTERS） | 貂蝉 压制 达摩 | 被压制英雄 | 貂蝉能在躲避技能同时很好的风筝达摩 | https://pvp.qq.com/web201605/herodetail/damo.shtml | 2026-10 |
| 12 | 貂蝉 → 项羽（COUNTERS） | 貂蝉 压制 项羽 | 被压制英雄 | 项羽不能很容易控制到灵活的貂蝉 | https://pvp.qq.com/web201605/herodetail/xiangyu.shtml | 2026-10 |
| 13 | 貂蝉 → 庄周（SYNERGIZES） | 貂蝉 与 庄周 搭档 | 最佳搭档 | 庄周：貂蝉是一个比较怕控制的英雄，需要一个队友去为她承受住来自敌人的打击，庄周大招可以为其解除大部分控制并增加免伤，能提高貂蝉的生存能力以及作战能力，是搭配貂蝉的不二选择。 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml | 2026-10 |
| 14 | 貂蝉 → 白起（SYNERGIZES） | 貂蝉 与 白起 搭档 | 最佳搭档 | 白起：面对切入型英雄，貂蝉需要拉开范围，而白起不仅能做到大招嘲讽，使貂蝉能在较安全的环境输出，也能在对方站位密集的地方群控(嘲讽效果)，让貂蝉尽情输出打出更多AOE真实伤害。 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml | 2026-10 |
| 15 | 貂蝉 → 露娜（COUNTERS） | 貂蝉 压制 露娜 | 压制英雄 | 露娜：貂蝉一般带净化居多，净化解控露娜成功断大一次都可以造成致命伤，貂蝉的2技能消失也可以完美躲避任何技能，把握好时机也能轻松断露娜的大降低他的威胁力，貂蝉在开大时的，2技能命中人后的cd是很快的，在团战中也有不输露娜的AOE输出。 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml | 2026-10 |
| 16 | 貂蝉 → 张飞（COUNTERS） | 貂蝉 压制 张飞 | 压制英雄 | 张飞：貂蝉在团战中的爆发很高（被动连爆），利用被动的真实伤害效果很好压制张飞这种技能的护盾的英雄，而且被动还带有减速效果，在单抓或者在团战中很好击杀或者压制住张飞，自身也不会遭受很高的伤害。 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml | 2026-10 |
| 17 | 张良 → 貂蝉（COUNTERS） | 张良 压制 貂蝉 | 被压制英雄 | 张良的硬控很容易控住貂蝉 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml | 2026-10 |
| 18 | 花木兰 → 貂蝉（COUNTERS） | 花木兰 压制 貂蝉 | 被压制英雄 | 花木兰的超高爆发输出能力能快速击杀走位不慎的貂蝉 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml | 2026-10 |
| 19 | 刘邦 → 貂蝉（SYNERGIZES） | 刘邦 与 貂蝉 搭档 | 最佳搭档 | 貂蝉：貂蝉是持续输出型英雄，在团战时刘邦的大招可以提高貂蝉的生存能力，正面团战时貂蝉开启大招配合刘邦大招的双抗和二技能的控制效果，可以拥有非常良好的输出环境，能轻松打出多段输出。 | https://pvp.qq.com/web201605/herodetail/liubang.shtml | 2026-10 |
| 20 | 貂蝉 → 牛魔（COUNTERS） | 貂蝉 压制 牛魔 | 被压制英雄 | 牛魔不能很容易控制到灵活的貂蝉 | https://pvp.qq.com/web201605/herodetail/niumo.shtml | 2026-10 |
| 21 | 貂蝉 → 虞姬（COUNTERS） | 貂蝉 压制 虞姬 | 被压制英雄 | 貂蝉的超高法术伤害和突进能力是虞姬无法抵挡的 | https://pvp.qq.com/web201605/herodetail/yuji.shtml | 2026-10 |
| 22 | 貂蝉 → 杨戬（COUNTERS） | 貂蝉 压制 杨戬 | 被压制英雄 | 貂蝉能在躲避技能同时很好的风筝杨戬 | https://pvp.qq.com/web201605/herodetail/yangjian.shtml | 2026-10 |
| 23 | 蔡文姬 → 貂蝉（COUNTERS） | 蔡文姬 压制 貂蝉 | 压制英雄 | 貂蝉：貂蝉是持续输出英雄，蔡文姬二技能追踪的连续两下控制很容易让貂蝉放空一个技能或者一个技能放不出来而自乱阵脚，1技能配合大招的恢复能力也能保护队友轻松逃生或反杀。 | https://pvp.qq.com/web201605/herodetail/caiwenji.shtml | 2026-10 |
| 24 | 貂蝉 → 哪吒（COUNTERS） | 貂蝉 压制 哪吒 | 被压制英雄 | 貂蝉能在躲避技能同时很好的风筝哪吒 | https://pvp.qq.com/web201605/herodetail/nezha.shtml | 2026-10 |
| 25 | 貂蝉 → 裴擒虎（COUNTERS） | 貂蝉 压制 裴擒虎 | 被压制英雄 | 貂蝉可及时的调整自身位置避免被裴擒虎折返跳跃命中，失去了爆发机会的裴擒虎，很难和貂蝉进行对拼 | https://pvp.qq.com/web201605/herodetail/peiqinhu.shtml | 2026-10 |
| 26 | 猪八戒 → 貂蝉（SYNERGIZES） | 猪八戒 与 貂蝉 搭档 | 最佳搭档 | 猪八戒凭借众多的控制效果和吸收伤害能力，能为貂蝉提供良好的输出空间 | https://pvp.qq.com/web201605/herodetail/zhubajie.shtml | 2026-10 |
| 27 | 貂蝉 → 澜（COUNTERS） | 貂蝉 压制 澜 | 被压制英雄 | 澜需近身打输出，而貂蝉可以通过二技能拉扯距离，有效规避掉澜的攻击。 | https://pvp.qq.com/web201605/herodetail/lan.shtml | 2026-10 |
| 28 | 赵怀真 → 貂蝉（COUNTERS） | 赵怀真 压制 貂蝉 | 压制英雄 | 赵怀真的大招可以吸收貂蝉的飞行物，使其无法触发印记。 | https://pvp.qq.com/web201605/herodetail/zhaohuaizhen.shtml | 2026-10 |
| 29 | 貂蝉 → 海诺（COUNTERS） | 貂蝉 压制 海诺 | 被压制英雄 | 貂蝉的2技能可以频繁躲避海诺的1技能，使海诺伤害无法叠上去 | https://pvp.qq.com/web201605/herodetail/hainuo.shtml | 2026-10 |
| 30 | 貂蝉 → 影（COUNTERS） | 貂蝉 压制 影 | 被压制英雄 | 影的二技能会为本身锁定朝向，面对较为灵活的貂蝉时影很难触碰到目标 | https://pvp.qq.com/web201605/herodetail/ying.shtml | 2026-10 |

#### 2.1.2 兰陵王（id=153，35 条）

- 官方页：https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml
- 分路：打野　上手难度：50　patch：2026-10

| # | 关系 | 语义 | 该页区块 | 理由（官方原文） | source URL | patch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 兰陵王 → 小乔（COUNTERS） | 兰陵王 压制 小乔 | 被压制英雄 | 兰陵王在团战中能够一套技能直接带走小乔 | https://pvp.qq.com/web201605/herodetail/xiaoqiao.shtml | 2026-10 |
| 2 | 兰陵王 → 妲己（COUNTERS） | 兰陵王 压制 妲己 | 被压制英雄 | 兰陵王的隐身和秒杀能力很容易接近妲己将其秒杀 | https://pvp.qq.com/web201605/herodetail/daji.shtml | 2026-10 |
| 3 | 兰陵王 → 嬴政（COUNTERS） | 兰陵王 压制 嬴政 | 被压制英雄 | 兰陵王的隐身和秒杀能力很容易接近嬴政将其秒杀 | https://pvp.qq.com/web201605/herodetail/yingzheng.shtml | 2026-10 |
| 4 | 兰陵王 → 孙尚香（COUNTERS） | 兰陵王 压制 孙尚香 | 被压制英雄 | 兰陵王的隐身和秒杀能力很容易接近孙尚香将其秒杀 | https://pvp.qq.com/web201605/herodetail/sunshangxiang.shtml | 2026-10 |
| 5 | 兰陵王 → 鲁班七号（COUNTERS） | 兰陵王 压制 鲁班七号 | 被压制英雄 | 鲁班没有位移技能，兰陵王的隐身和秒杀能力很容易接近鲁班将其秒杀 | https://pvp.qq.com/web201605/herodetail/lubanqihao.shtml | 2026-10 |
| 6 | 钟无艳 → 兰陵王（COUNTERS） | 钟无艳 压制 兰陵王 | 压制英雄 | 兰陵王：兰陵王作为一个自身没有位移技能的刺客，虽然大招隐身非常厉害，钟无艳可以在兰陵王靠近时靠近我方后排，释放一二技能，不给兰陵王近身的机会。即便敌方兰陵王隐身秒掉我方后排，也会被钟无艳石化，以命换命。 | https://pvp.qq.com/web201605/herodetail/zhongwuyan.shtml | 2026-10 |
| 7 | 兰陵王 → 孙膑（COUNTERS） | 兰陵王 压制 孙膑 | 被压制英雄 | 兰陵王的隐身和秒杀能力很容易接近孙膑将其秒杀 | https://pvp.qq.com/web201605/herodetail/sunbin.shtml | 2026-10 |
| 8 | 兰陵王 → 扁鹊（COUNTERS） | 兰陵王 压制 扁鹊 | 被压制英雄 | 兰陵王的隐身和秒杀能力很容易接近扁鹊将其秒杀 | https://pvp.qq.com/web201605/herodetail/bianque.shtml | 2026-10 |
| 9 | 兰陵王 → 周瑜（COUNTERS） | 兰陵王 压制 周瑜 | 被压制英雄 | 兰陵王大招的隐身近身和二段位移斩杀，十分克制需要布置战场的周瑜 | https://pvp.qq.com/web201605/herodetail/zhouyv.shtml | 2026-10 |
| 10 | 兰陵王 → 狄仁杰（COUNTERS） | 兰陵王 压制 狄仁杰 | 被压制英雄 | 狄仁杰没有位移技能，兰陵王的隐身和秒杀能力很容易接近他将其秒杀 | https://pvp.qq.com/web201605/herodetail/direnjie.shtml | 2026-10 |
| 11 | 兰陵王 → 武则天（COUNTERS） | 兰陵王 压制 武则天 | 被压制英雄 | 兰陵王在团战中能够一套技能直接带走武则天 | https://pvp.qq.com/web201605/herodetail/wuzetian.shtml | 2026-10 |
| 12 | 兰陵王 → 安琪拉（COUNTERS） | 兰陵王 压制 安琪拉 | 被压制英雄 | 兰陵王在团战中能够一套技能直接带走安琪拉 | https://pvp.qq.com/web201605/herodetail/anqila.shtml | 2026-10 |
| 13 | 刘邦 → 兰陵王（COUNTERS） | 刘邦 压制 兰陵王 | 压制英雄 | 兰陵王：兰陵王的输出手法是2技能后的一套组合技能秒杀，作为一个高强度的坦克，在中后期兰陵王很难有效击杀刘邦，在单带时可以利用技能减速和控制效果与兰陵王正面刚，在团战时可以用大招保护己方输出防止被兰陵王击杀，落地后的2技能可以控制敌方兰陵王，为己方输出争取逃生和反杀的机会，能克制兰陵王。 | https://pvp.qq.com/web201605/herodetail/liubang.shtml | 2026-10 |
| 14 | 兰陵王 → 王昭君（COUNTERS） | 兰陵王 压制 王昭君 | 被压制英雄 | 兰陵王在团战中能够一套技能直接带走王昭君 | https://pvp.qq.com/web201605/herodetail/wangzhaojun.shtml | 2026-10 |
| 15 | 兰陵王 → 宫本武藏（SYNERGIZES） | 兰陵王 与 宫本武藏 搭档 | 最佳搭档 | 宫本武藏：兰陵王独立作战能力比较强，前期可以频繁游走抓人。宫本武藏拥有指向留人的控制，能先手快速留住敌方英雄，提高兰陵王连招刺杀的容错率；宫本武藏的特性是高伤害，高爆发，短期高伤害可以快速压低目标血线，让兰陵王的2技能收益更高。 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml | 2026-10 |
| 16 | 兰陵王 → 诸葛亮（SYNERGIZES） | 兰陵王 与 诸葛亮 搭档 | 最佳搭档 | 诸葛亮：兰陵王游走抓人的时候，经常会让敌人残血闪现逃走，诸葛的大招就可以远程收割敌方残血英雄，诸葛有位移很适合与兰陵王中野联动的打法；团战的时候，兰陵王是单体高爆发伤害英雄，诸葛的被动加1技能可以弥补兰陵王作为刺客的不足，可以消耗敌方英雄，为兰陵王创造单杀条件或者创造切入时机。 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml | 2026-10 |
| 17 | 兰陵王 → 鲁班七号（COUNTERS） | 兰陵王 压制 鲁班七号 | 压制英雄 | 鲁班七号：无位移技能的英雄，兰陵王几乎是他们最大的威胁，高爆发一套流的特性，可以非常好的压制鲁班这个控制技能不多，无自保能力的英雄。 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml | 2026-10 |
| 18 | 兰陵王 → 李白（COUNTERS） | 兰陵王 压制 李白 | 压制英雄 | 李白：李白在初期的伤害能力比较差，单挑无法打赢兰陵王，被兰陵王2技能加1技能组合技能后会直接残血，兰陵王可以在野区抢李白的资源，压制李白无法发育，寻找机会击杀李白，在中后期2技能配合1技能控制大招也可以直接秒杀李白、 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml | 2026-10 |
| 19 | 项羽 → 兰陵王（COUNTERS） | 项羽 压制 兰陵王 | 被压制英雄 | 项羽能在兰陵王切入后将其控制并推开，限制他的输出 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml | 2026-10 |
| 20 | 张良 → 兰陵王（COUNTERS） | 张良 压制 兰陵王 | 被压制英雄 | 张良的硬控能控住兰陵王将其击杀 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml | 2026-10 |
| 21 | 李元芳 → 兰陵王（COUNTERS） | 李元芳 压制 兰陵王 | 压制英雄 | 兰陵王：兰陵王的核心玩法是隐身后先手秒杀敌方核心输出点，有李元芳的被动在可以轻松探测到敌方兰陵王的位置和动态，强大的反隐效果可以让兰陵王失去gank己方核心输出位的机会，躲避好兰陵王的2技能后站撸也可以轻松击杀兰陵王。 | https://pvp.qq.com/web201605/herodetail/liyuanfang.shtml | 2026-10 |
| 22 | 兰陵王 → 李元芳（COUNTERS） | 兰陵王 压制 李元芳 | 被压制英雄 | 兰陵王的隐身和秒杀能力很容易接近李元芳将其秒杀 | https://pvp.qq.com/web201605/herodetail/liyuanfang.shtml | 2026-10 |
| 23 | 雅典娜 → 兰陵王（COUNTERS） | 雅典娜 压制 兰陵王 | 压制英雄 | 兰陵王：雅典娜的一技能和三技能都可以提供护盾和免控，运用得当可以抵挡兰陵王二技能的二段伤害，以及眩晕效果。在角色定位上，兰陵王属于刺客，身板较弱，而雅典娜是半肉战士，并且可以让兰陵王二技能大部分效果无效化。在机动性上，雅典娜的移速比兰陵王还快，位移技能也更多，从总体上对兰陵王进行克制。 | https://pvp.qq.com/web201605/herodetail/yadianna.shtml | 2026-10 |
| 24 | 兰陵王 → 蔡文姬（COUNTERS） | 兰陵王 压制 蔡文姬 | 被压制英雄 | 兰陵王的隐身和秒杀能力很容易接近蔡文姬将其秒杀 | https://pvp.qq.com/web201605/herodetail/caiwenji.shtml | 2026-10 |
| 25 | 太乙真人 → 兰陵王（COUNTERS） | 太乙真人 压制 兰陵王 | 压制英雄 | 兰陵王：面对只有一次切入机会的兰陵王，太乙真人的控制牵制能力（开一技能走在后排身边，二技能主动勾兰陵王）都可以降低被兰陵王切入的概率，同时大招所给予的复活也明显克制了兰陵王切入机会只有一次的设定，相比较同类辅助如刘邦孙膑，太乙真人可以更好的压制兰陵王，避免被切入。 | https://pvp.qq.com/web201605/herodetail/taiyizhenren.shtml | 2026-10 |
| 26 | 兰陵王 → 诸葛亮（COUNTERS） | 兰陵王 压制 诸葛亮 | 被压制英雄 | 诸葛亮容易被兰陵王抓住后秒掉 | https://pvp.qq.com/web201605/herodetail/zhugeliang.shtml | 2026-10 |
| 27 | 兰陵王 → 黄忠（COUNTERS） | 兰陵王 压制 黄忠 | 被压制英雄 | 黄忠容易被兰陵王抓住后秒掉 | https://pvp.qq.com/web201605/herodetail/huangzhong.shtml | 2026-10 |
| 28 | 兰陵王 → 干将莫邪（COUNTERS） | 兰陵王 压制 干将莫邪 | 被压制英雄 | 干将莫邪没有技能可以抵抗兰陵王的秒杀能力 | https://pvp.qq.com/web201605/herodetail/ganjiangmoye.shtml | 2026-10 |
| 29 | 鬼谷子 → 兰陵王（COUNTERS） | 鬼谷子 压制 兰陵王 | 压制英雄 | 兰陵王：兰陵王的核心玩法是隐身靠近敌方核心输出位，寻找时机切死敌方后排，而鬼谷子大招开启时会触发反隐效果，可以轻松发现兰陵王的身位，配合队友利用2技能控制1技能的减少抗性轻松秒掉兰陵王。 | https://pvp.qq.com/web201605/herodetail/guiguzi.shtml | 2026-10 |
| 30 | 兰陵王 → 女娲（COUNTERS） | 兰陵王 压制 女娲 | 被压制英雄 | 女娲无法预知兰陵王会从哪个方向进攻，其高额的爆发也会让女娲感受到压力 | https://pvp.qq.com/web201605/herodetail/nvwa.shtml | 2026-10 |
| 31 | 兰陵王 → 元歌（COUNTERS） | 兰陵王 压制 元歌 | 被压制英雄 | 元歌本体还是惧怕爆发袭击，兰陵王凭借隐身能力能逼迫元歌放弃操作傀儡，轻松击杀 | https://pvp.qq.com/web201605/herodetail/yuange.shtml | 2026-10 |
| 32 | 兰陵王 → 伽罗（COUNTERS） | 兰陵王 压制 伽罗 | 被压制英雄 | 暗中前来的兰陵王让伽罗的视野能力失去意义，突出的爆发能力更会直接将伽罗秒杀 | https://pvp.qq.com/web201605/herodetail/jialuo.shtml | 2026-10 |
| 33 | 兰陵王 → 沈梦溪（COUNTERS） | 兰陵王 压制 沈梦溪 | 被压制英雄 | 沈梦溪非常害怕爆发伤害，兰陵王足以在沈梦溪反应过来之前将其消灭。 | https://pvp.qq.com/web201605/herodetail/shenmengxi.shtml | 2026-10 |
| 34 | 瑶 → 兰陵王（COUNTERS） | 瑶 压制 兰陵王 | 压制英雄 | 在瑶的帮助下兰陵王很难秒杀瑶的队友，而优先针对瑶也会被其被动化解 | https://pvp.qq.com/web201605/herodetail/yao.shtml | 2026-10 |
| 35 | 兰陵王 → 蒙犽（COUNTERS） | 兰陵王 压制 蒙犽 | 被压制英雄 | 蒙犽没有位移也没有反打的技能，面对爆发力高的刺客几乎只能依靠队友保护 | https://pvp.qq.com/web201605/herodetail/mengya.shtml | 2026-10 |

#### 2.1.3 亚瑟（id=166，7 条）

- 官方页：https://pvp.qq.com/web201605/herodetail/yase.shtml
- 分路：对抗路 / 打野　上手难度：20　patch：2026-10

| # | 关系 | 语义 | 该页区块 | 理由（官方原文） | source URL | patch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 亚瑟 → 鲁班七号（SYNERGIZES） | 亚瑟 与 鲁班七号 搭档 | 最佳搭档 | 所有己方ADC：当己方ADC遭到敌方干扰进攻时，亚瑟的沉默等控制可以配合我方ADC击杀敌方，技能效果非常适合保护己方ADC。 | https://pvp.qq.com/web201605/herodetail/yase.shtml | 2026-10 |
| 2 | 亚瑟 → 阿轲（SYNERGIZES） | 亚瑟 与 阿轲 搭档 | 最佳搭档 | 阿轲：亚瑟的一技能非常频繁，对敌方单体的沉默能力非常突出，而阿轲正好也是对单体输出非常强的英雄，且机动性很高，配合亚瑟的控制可以轻松的击杀目标。 | https://pvp.qq.com/web201605/herodetail/yase.shtml | 2026-10 |
| 3 | 亚瑟 → 韩信（COUNTERS） | 亚瑟 压制 韩信 | 压制英雄 | 韩信：韩信是个非常依赖技能的英雄，亚瑟的一技能沉默可以非常轻松的打断韩信的攻势，二技能和大招可以轻松将韩信的血量进行消耗。 | https://pvp.qq.com/web201605/herodetail/yase.shtml | 2026-10 |
| 4 | 亚瑟 → 阿轲（COUNTERS） | 亚瑟 压制 阿轲 | 压制英雄 | 阿轲：根据阿轲的隐身标记来判断出阿轲的进攻目标，守株待兔等待阿轲的进攻，现身就立即打出沉默来保护己方脆弱目标，甚至可以直接使用大招配合队友控制击杀阿轲。 | https://pvp.qq.com/web201605/herodetail/yase.shtml | 2026-10 |
| 5 | 项羽 → 亚瑟（COUNTERS） | 项羽 压制 亚瑟 | 被压制英雄 | 亚瑟入场后，项羽能将他推开或控制，限制对友方的输出与控制 | https://pvp.qq.com/web201605/herodetail/yase.shtml | 2026-10 |
| 6 | 孙尚香 → 亚瑟（COUNTERS） | 孙尚香 压制 亚瑟 | 被压制英雄 | 孙尚香很容易风筝亚瑟 | https://pvp.qq.com/web201605/herodetail/yase.shtml | 2026-10 |
| 7 | 百里守约 → 亚瑟（COUNTERS） | 百里守约 压制 亚瑟 | 压制英雄 | 没有多段位移的战士不会对百里守约造成太大的威胁 | https://pvp.qq.com/web201605/herodetail/bailishouyue.shtml | 2026-10 |

#### 2.1.4 后羿（id=169，31 条）

- 官方页：https://pvp.qq.com/web201605/herodetail/houyi.shtml
- 分路：发育路　上手难度：30　patch：2026-10

| # | 关系 | 语义 | 该页区块 | 理由（官方原文） | source URL | patch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 后羿 → 廉颇（COUNTERS） | 后羿 压制 廉颇 | 被压制英雄 | 后羿普攻有减速效果，很容易风筝廉颇 | https://pvp.qq.com/web201605/herodetail/lianpo.shtml | 2026-10 |
| 2 | 赵云 → 后羿（COUNTERS） | 赵云 压制 后羿 | 压制英雄 | 后羿：团战中，赵云只要找到后羿的位置，就可以先手大后羿，如果是没有闪现的后羿，那么后羿基本上就被赵云一套带走。gank时，在前中期，后羿没有位移的，并且在近距离后羿的大招也没有很好的发挥，所以我们可以优先选择gank后羿，配合边路英雄，一旦大招命中后羿就插翅难逃，很好的限制了后羿的发育。 | https://pvp.qq.com/web201605/herodetail/zhaoyun.shtml | 2026-10 |
| 3 | 庄周 → 后羿（COUNTERS） | 庄周 压制 后羿 | 压制英雄 | 后羿：即使是出肉装的庄周，后期伤害也异常可怕，自身技能特点也让他根本不会被风筝。叠起被动的伤害能轻易击杀没有位移的脆皮，对此类英雄进行强力压制。 | https://pvp.qq.com/web201605/herodetail/zhuangzhou.shtml | 2026-10 |
| 4 | 心魔六耳 → 后羿（COUNTERS） | 心魔六耳 压制 后羿 | 压制英雄 | 后羿缺乏位移手段，心魔六耳可利用二技能快速逼近，一技能控制后打出完整连招，后羿难以反应逃脱 | https://pvp.qq.com/web201605/herodetail/xinmoliuer.shtml | 2026-10 |
| 5 | 安琪拉 → 后羿（COUNTERS） | 安琪拉 压制 后羿 | 压制英雄 | 后羿：针对后羿类型的后排无位移英雄，可以在草丛伏击，先手2技能打中后接1技能大招可以轻松秒杀敌方英雄。 | https://pvp.qq.com/web201605/herodetail/anqila.shtml | 2026-10 |
| 6 | 姜子牙 → 后羿（COUNTERS） | 姜子牙 压制 后羿 | 压制英雄 | 后羿较为笨重，容易被姜子牙一套技能控制和击败 | https://pvp.qq.com/web201605/herodetail/jiangziya.shtml | 2026-10 |
| 7 | 张良 → 后羿（SYNERGIZES） | 张良 与 后羿 搭档 | 最佳搭档 | 张良的先手能力和长时间控制，给后羿提供了黏住敌人并且持续输出的环境 | https://pvp.qq.com/web201605/herodetail/zhangliang.shtml | 2026-10 |
| 8 | 娜可露露 → 后羿（COUNTERS） | 娜可露露 压制 后羿 | 压制英雄 | 后羿：后羿作为无位移的射手，极易被游走的娜可露露gank，灵巧的娜可露露可以躲开其控制并高效率中击杀落单的后羿。 | https://pvp.qq.com/web201605/herodetail/nakelulu.shtml | 2026-10 |
| 9 | 后羿 → 钟馗（SYNERGIZES） | 后羿 与 钟馗 搭档 | 最佳搭档 | 一旦敌人被后羿的大招命中，那么钟馗的钩子几乎是百发百中。 | https://pvp.qq.com/web201605/herodetail/houyi.shtml | 2026-10 |
| 10 | 后羿 → 牛魔（SYNERGIZES） | 后羿 与 牛魔 搭档 | 最佳搭档 | 后羿是没有位移的射手，在团战中比较依赖队友的保护，牛魔的被动可以给后羿提供防御属性，而他极强的控制技能，可以帮助后羿逃离对手的攻击范围。 | https://pvp.qq.com/web201605/herodetail/houyi.shtml | 2026-10 |
| 11 | 后羿 → 百里守约（COUNTERS） | 后羿 压制 百里守约 | 压制英雄 | 百里守约释放2技能蓄力阶段是不会移动的，利用这个时机对他释放大招，然后集火攻击他。 | https://pvp.qq.com/web201605/herodetail/houyi.shtml | 2026-10 |
| 12 | 后羿 → 张良（COUNTERS） | 后羿 压制 张良 | 压制英雄 | 当张良释放大招控制住队友的时候，立即释放大招攻击张良，可以打断张良大招保护队友。 | https://pvp.qq.com/web201605/herodetail/houyi.shtml | 2026-10 |
| 13 | 妲己 → 后羿（COUNTERS） | 妲己 压制 后羿 | 被压制英雄 | 后羿自身比较脆弱，一旦遇到高爆发的法师，可能会被一套带走。 | https://pvp.qq.com/web201605/herodetail/houyi.shtml | 2026-10 |
| 14 | 李白 → 后羿（COUNTERS） | 李白 压制 后羿 | 被压制英雄 | 李白释放技能的时候，有一个短暂的不可选中的过程，可以轻松躲避后羿的关键技能。 | https://pvp.qq.com/web201605/herodetail/houyi.shtml | 2026-10 |
| 15 | 张飞 → 后羿（SYNERGIZES） | 张飞 与 后羿 搭档 | 最佳搭档 | 后羿：后羿也是依赖队友保护的英雄之一，同时也是最具嘲讽特色的英雄，所有刺客都想要第一时间击杀后羿，因为后羿的输出极为恐怖。张飞为后羿提供的护盾至少可以抵挡对面刺客的一个技能，同时一技能能够将对手与后羿保持一定距离，而大招更能够帮助后羿提供更好的输出环境，最大化后羿的输出。 | https://pvp.qq.com/web201605/herodetail/zhangfei.shtml | 2026-10 |
| 16 | 哪吒 → 后羿（COUNTERS） | 哪吒 压制 后羿 | 压制英雄 | 后羿：后羿作为无位移的射手，极度依赖队友保护，而哪吒大招可以做到团战时无视后羿队友直接冲锋，大招的韧性加成以及二技能的减伤能够为哪吒提供续航能力，打出更多真实伤害，一技能提供的移动速度也能让后羿无所遁形。 | https://pvp.qq.com/web201605/herodetail/nezha.shtml | 2026-10 |
| 17 | 铠 → 后羿（COUNTERS） | 铠 压制 后羿 | 压制英雄 | 没位移的射手英雄要离铠远一点哦 | https://pvp.qq.com/web201605/herodetail/kai.shtml | 2026-10 |
| 18 | 盾山 → 后羿（COUNTERS） | 盾山 压制 后羿 | 压制英雄 | 后羿不仅不太灵活容易被盾山抛回，并且后羿依赖的强大正面射击能力被盾山完美克制 | https://pvp.qq.com/web201605/herodetail/dunshan.shtml | 2026-10 |
| 19 | 上官婉儿 → 后羿（COUNTERS） | 上官婉儿 压制 后羿 | 压制英雄 | 上官婉儿能在远处开始累积冲刺次数，同时快速逼近射手，随后释放大招，后羿靠自身几乎无法阻止 | https://pvp.qq.com/web201605/herodetail/shangguanwaner.shtml | 2026-10 |
| 20 | 猪八戒 → 后羿（COUNTERS） | 猪八戒 压制 后羿 | 压制英雄 | 猪八戒出色的开团能力，会让后排英雄十分危险，常常会被强行控制开启团战 | https://pvp.qq.com/web201605/herodetail/zhubajie.shtml | 2026-10 |
| 21 | 瑶 → 后羿（SYNERGIZES） | 瑶 与 后羿 搭档 | 最佳搭档 | 持续输出的射手在瑶附身后，全力输出伤害并不用担心突袭 | https://pvp.qq.com/web201605/herodetail/yao.shtml | 2026-10 |
| 22 | 云中君 → 后羿（COUNTERS） | 云中君 压制 后羿 | 压制英雄 | 无位移射手非常容易被云中君卷起带走 | https://pvp.qq.com/web201605/herodetail/yunzhongjun.shtml | 2026-10 |
| 23 | 鲁班大师 → 后羿（COUNTERS） | 鲁班大师 压制 后羿 | 压制英雄 | 缺乏硬控和灵活性的脆皮，走位不慎时容易被鲁班大师先手控制 | https://pvp.qq.com/web201605/herodetail/lubandashi.shtml | 2026-10 |
| 24 | 夏洛特 → 后羿（COUNTERS） | 夏洛特 压制 后羿 | 压制英雄 | 攻速对于后裔输出的影响较大，缺乏位移也让夏洛特的命中机会得以增大 | https://pvp.qq.com/web201605/herodetail/xialuote.shtml | 2026-10 |
| 25 | 后羿 → 艾琳（COUNTERS） | 后羿 压制 艾琳 | 被压制英雄 | 后羿可以先手控制艾琳，且站桩输出能力高于艾琳。 | https://pvp.qq.com/web201605/herodetail/ailin.shtml | 2026-10 |
| 26 | 云缨 → 后羿（COUNTERS） | 云缨 压制 后羿 | 压制英雄 | 不太灵活的射手面对云缨的大招较难躲避，容易被连招击杀 | https://pvp.qq.com/web201605/herodetail/yunying.shtml | 2026-10 |
| 27 | 桑启 → 后羿（SYNERGIZES） | 桑启 与 后羿 搭档 | 最佳搭档 | 持续给射手提供治疗 | https://pvp.qq.com/web201605/herodetail/sangqi.shtml | 2026-10 |
| 28 | 赵怀真 → 后羿（SYNERGIZES） | 赵怀真 与 后羿 搭档 | 最佳搭档 | 赵怀真缺乏持续输出，后羿的稳定远程伤害可以防止敌人残血逃走。 | https://pvp.qq.com/web201605/herodetail/zhaohuaizhen.shtml | 2026-10 |
| 29 | 影 → 后羿（COUNTERS） | 影 压制 后羿 | 压制英雄 | 影面对没有位移的英雄时，二技能有较高概率实现输出最大化 | https://pvp.qq.com/web201605/herodetail/ying.shtml | 2026-10 |
| 30 | 元流之子(射手) → 后羿（COUNTERS） | 元流之子(射手) 压制 后羿 | 压制英雄 | 面对后裔时可以更主动地出击，利用二技能位移或大招连放的浮空效果规避后裔的大招反扑 | https://pvp.qq.com/web201605/herodetail/yuanliuzhizi_archer.shtml | 2026-10 |
| 31 | 卢雅那 → 后羿（COUNTERS） | 卢雅那 压制 后羿 | 压制英雄 | 后羿依靠普通攻击进行输出，致盲效果完美克制后羿，同时卢雅那高机动性能够拉扯后羿 | https://pvp.qq.com/web201605/herodetail/luyana.shtml | 2026-10 |

#### 2.1.5 东皇太一（id=187，17 条）

- 官方页：https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml
- 分路：游走 / 对抗路　上手难度：40　patch：2026-10

| # | 关系 | 语义 | 该页区块 | 理由（官方原文） | source URL | patch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 小乔 → 东皇太一（COUNTERS） | 小乔 压制 东皇太一 | 压制英雄 | 东皇太一：因为通过二技能命中之后的被动位移加速以及通过不断一技能骚扰，充分的拉开与东皇的距离，使得他身边的能量体无法贴近小乔进行回血，只能被迫放风筝。 | https://pvp.qq.com/web201605/herodetail/xiaoqiao.shtml | 2026-10 |
| 2 | 孙尚香 → 东皇太一（SYNERGIZES） | 孙尚香 与 东皇太一 搭档 | 最佳搭档 | 东皇太一：东皇太一的大招可以控制敌方英雄，是应对敌方突进英雄的不二选择，东皇的超强回复能力注定了东皇也是一名合格的坦克，有东皇在前排吸收敌方火力，后排的孙尚香就可以安心输出。 | https://pvp.qq.com/web201605/herodetail/sunshangxiang.shtml | 2026-10 |
| 3 | 孙尚香 → 东皇太一（COUNTERS） | 孙尚香 压制 东皇太一 | 压制英雄 | 东皇太一：东皇太一大招范围小，只有能量球触碰到敌方英雄才会回血，所以，孙尚香的超远射程就可以轻松克制他，东皇的二技能虽然控制长达一秒，但是延迟太高，面对拥有位移的孙尚香命中率低。大招作为强力控制，范围是硬伤，无法靠近孙尚香就会被消耗至死。 | https://pvp.qq.com/web201605/herodetail/sunshangxiang.shtml | 2026-10 |
| 4 | 扁鹊 → 东皇太一（COUNTERS） | 扁鹊 压制 东皇太一 | 压制英雄 | 东皇太一：东皇太一初期具有较强的入侵野区能力，扁鹊和其他中单不同，扁鹊主要靠普攻叠被动来打更多输出的，所以当东皇太一来己方蓝buff时，扁鹊可以通过普攻和技能不断对他进行消耗，可以避免了近战英雄和东皇太一站撸的情况。使东皇太一初期入侵能力下降，避免敌方在初期拿到节奏。 | https://pvp.qq.com/web201605/herodetail/bianque.shtml | 2026-10 |
| 5 | 心魔六耳 → 东皇太一（SYNERGIZES） | 心魔六耳 与 东皇太一 搭档 | 最佳搭档 | 东皇太一可以提供强力的全团控制，为心魔六耳创造切入时机，配合大招爆发形成高额连携伤害 | https://pvp.qq.com/web201605/herodetail/xinmoliuer.shtml | 2026-10 |
| 6 | 东皇太一 → 芈月（COUNTERS） | 东皇太一 压制 芈月 | 被压制英雄 | 东皇太一：拥有硬控的英雄可以很好的控制住芈月让她无法随心所欲施放技能 | https://pvp.qq.com/web201605/herodetail/miyue.shtml | 2026-10 |
| 7 | 马可波罗 → 东皇太一（COUNTERS） | 马可波罗 压制 东皇太一 | 压制英雄 | 东皇太一：东皇比较克制灵活的英雄，马可波罗不仅仅是灵活，还有拥射程优势，可以在东皇控制范围外进行攻击 | https://pvp.qq.com/web201605/herodetail/makeboluo.shtml | 2026-10 |
| 8 | 虞姬 → 东皇太一（SYNERGIZES） | 虞姬 与 东皇太一 搭档 | 最佳搭档 | 东皇太一：虞姬的特性，非常害怕刺客型法师切入，所以她需要一个能让她免于法师切入的英雄，而东皇太一就是这样一个非常合适的英雄。由于东皇太一大招的的特性，意味着只要有法师切入，一定会被控制住，而虞姬的高爆发伤害，几乎肯定能击杀来切入的脆皮法师，更能让虞姬在团战中更加肆无忌惮的输出。 | https://pvp.qq.com/web201605/herodetail/yuji.shtml | 2026-10 |
| 9 | 东皇太一 → 马可波罗（SYNERGIZES） | 东皇太一 与 马可波罗 搭档 | 最佳搭档 | 马可波罗：东皇太一的大招能够很好的保护己方核心输出，敌方输出突进过来时，东皇太一开大可以轻松压制，马可波罗的1技能爆炸输出伤害也很高，可以配合东皇太一轻松秒杀敌方刺客，由于刺客切入身板比较脆，血量会比东皇太一低很多，在减员敌方一名成员后依旧可以发挥自己的作用在团战中吸收伤害做前排。 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml | 2026-10 |
| 10 | 东皇太一 → 阿轲（SYNERGIZES） | 东皇太一 与 阿轲 搭档 | 最佳搭档 | 阿轲：东皇太一长时间的稳定控制，可以让阿轲轻松完成背击，造成大量伤害击败一名成员并刷新技能产生收割的效果。 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml | 2026-10 |
| 11 | 东皇太一 → 露娜（COUNTERS） | 东皇太一 压制 露娜 | 压制英雄 | 露娜：4级后的团战，己方队友都在时，露娜切入直接大招集火秒杀即可，有东皇太一时的团战，露娜很少有先手开团和poke的机会，也可以寻找时机强开露娜，即使自己牺牲，能换掉露娜也是大赚的。 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml | 2026-10 |
| 12 | 东皇太一 → 太乙真人（COUNTERS） | 东皇太一 压制 太乙真人 | 压制英雄 | 太乙真人：东皇太一大招太乙真人的时候，太乙真人是不能释放大招的，初期游走对抗东皇太一的伤害和恢复能力不输太乙真人，面对AP太乙真人入侵野区也能很好的针对和克制，包括技能细节，太乙真人开1技能蓄力期间，东皇太一大招太乙真人后爆炸伤害都会施加给太乙真人，可以很好的克制太乙真人。 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml | 2026-10 |
| 13 | 蔡文姬 → 东皇太一（COUNTERS） | 蔡文姬 压制 东皇太一 | 被压制英雄 | 蔡文姬拥有短时间的强力回复能力，让东皇太一的大招伤敌500自损1000 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml | 2026-10 |
| 14 | 牛魔 → 东皇太一（COUNTERS） | 牛魔 压制 东皇太一 | 被压制英雄 | 敌方集火东皇大住的敌人时牛魔能很容易找准机会反打控制住多个英雄 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml | 2026-10 |
| 15 | 东皇太一 → 百里玄策（COUNTERS） | 东皇太一 压制 百里玄策 | 被压制英雄 | 强力控制对于百里玄策来说是十分致命的威胁，几乎不敢先手入场 | https://pvp.qq.com/web201605/herodetail/bailixuance.shtml | 2026-10 |
| 16 | 东皇太一 → 公孙离（COUNTERS） | 东皇太一 压制 公孙离 | 被压制英雄 | 阿离面对强控时，会很难进场输出，较短的输出距离会被东皇太一大招克制 | https://pvp.qq.com/web201605/herodetail/gongsunli.shtml | 2026-10 |
| 17 | 东皇太一 → 司马懿（COUNTERS） | 东皇太一 压制 司马懿 | 被压制英雄 | 硬控十分克制刺客的突袭，会让司马懿无法进场输出 | https://pvp.qq.com/web201605/herodetail/simayi.shtml | 2026-10 |

## 3. 语料清单（C1 官方聚合 / C2 LLM 生成）

共 138 篇。C1 = 官方原文聚合（`data_source=real`，与图谱关系同源）；C2 = 基于官方事实撰写的对线思路（`data_source=llm_assisted`）。

- **C1 133 篇**（每英雄一篇官方聚合，覆盖 133 英雄）；**C2 5 篇**（M1a 已审，未改动）。C1:C2 ≈ 27:1，满足「C1 为主干、≥3:1」要求。

### 3.1 llm_assisted 条目（**单独列出，集中审核**）

| doc_id | 主题 | 涉及英雄 | 事实来源（官方页） | 文本性质 |
| --- | --- | --- | --- | --- |
| c2-diaochan-laning | 对线思路 | 貂蝉 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml | LLM 生成，事实源为官方页面 |
| c2-donghuangtaiyi-roaming | 对线思路 | 东皇太一 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml | LLM 生成，事实源为官方页面 |
| c2-houyi-laning | 对线思路 | 后羿 | https://pvp.qq.com/web201605/herodetail/houyi.shtml | LLM 生成，事实源为官方页面 |
| c2-lanlingwang-jungle | 对线思路 | 兰陵王 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml | LLM 生成，事实源为官方页面 |
| c2-yase-laning | 对线思路 | 亚瑟 | https://pvp.qq.com/web201605/herodetail/yase.shtml | LLM 生成，事实源为官方页面 |

> 说明：C2 的 `source_type=official`（事实出自官方页），`data_source=llm_assisted`（文本为生成）。两字段分工见 DECISIONS.md。审核重点：表达是否自然、有无模板腔、是否与官方事实一致。

### 3.2 C1 官方聚合条目（原文，无需逐句审）

| doc_id | 主题 | 涉及英雄 | 事实来源（官方页） |
| --- | --- | --- | --- |
| c1-aguduo-official | 英雄资料 | 阿古朵 | https://pvp.qq.com/web201605/herodetail/aguduo.shtml |
| c1-ailin-official | 英雄资料 | 艾琳 | https://pvp.qq.com/web201605/herodetail/ailin.shtml |
| c1-ake-official | 英雄资料 | 阿轲 | https://pvp.qq.com/web201605/herodetail/ake.shtml |
| c1-anqila-official | 英雄资料 | 安琪拉 | https://pvp.qq.com/web201605/herodetail/anqila.shtml |
| c1-aoyin-official | 英雄资料 | 敖隐 | https://pvp.qq.com/web201605/herodetail/aoyin.shtml |
| c1-bailishouyue-official | 英雄资料 | 百里守约 | https://pvp.qq.com/web201605/herodetail/bailishouyue.shtml |
| c1-bailixuance-official | 英雄资料 | 百里玄策 | https://pvp.qq.com/web201605/herodetail/bailixuance.shtml |
| c1-baiqi-official | 英雄资料 | 白起 | https://pvp.qq.com/web201605/herodetail/baiqi.shtml |
| c1-bianque-official | 英雄资料 | 扁鹊 | https://pvp.qq.com/web201605/herodetail/bianque.shtml |
| c1-buzhihuowu-official | 英雄资料 | 不知火舞 | https://pvp.qq.com/web201605/herodetail/buzhihuowu.shtml |
| c1-caiwenji-official | 英雄资料 | 蔡文姬 | https://pvp.qq.com/web201605/herodetail/caiwenji.shtml |
| c1-cang-official | 英雄资料 | 苍 | https://pvp.qq.com/web201605/herodetail/cang.shtml |
| c1-caocao-official | 英雄资料 | 曹操 | https://pvp.qq.com/web201605/herodetail/caocao.shtml |
| c1-change-official | 英雄资料 | 嫦娥 | https://pvp.qq.com/web201605/herodetail/change.shtml |
| c1-chengyaojin-official | 英雄资料 | 程咬金 | https://pvp.qq.com/web201605/herodetail/chengyaojin.shtml |
| c1-chicha-official | 英雄资料 | 蚩奼 | https://pvp.qq.com/web201605/herodetail/chicha.shtml |
| c1-daji-official | 英雄资料 | 妲己 | https://pvp.qq.com/web201605/herodetail/daji.shtml |
| c1-damo-official | 英雄资料 | 达摩 | https://pvp.qq.com/web201605/herodetail/damo.shtml |
| c1-daqiao-official | 英雄资料 | 大乔 | https://pvp.qq.com/web201605/herodetail/daqiao.shtml |
| c1-dasiming-official | 英雄资料 | 大司命 | https://pvp.qq.com/web201605/herodetail/dasiming.shtml |
| c1-dayu-official | 英雄资料 | 大禹 | https://pvp.qq.com/web201605/herodetail/dayu.shtml |
| c1-dianwei-official | 英雄资料 | 典韦 | https://pvp.qq.com/web201605/herodetail/dianwei.shtml |
| c1-diaochan-official | 英雄资料 | 貂蝉 | https://pvp.qq.com/web201605/herodetail/diaochan.shtml |
| c1-direnjie-official | 英雄资料 | 狄仁杰 | https://pvp.qq.com/web201605/herodetail/direnjie.shtml |
| c1-dongfangyao-official | 英雄资料 | 曜 | https://pvp.qq.com/web201605/herodetail/dongfangyao.shtml |
| c1-donghuangtaiyi-official | 英雄资料 | 东皇太一 | https://pvp.qq.com/web201605/herodetail/donghuangtaiyi.shtml |
| c1-dunshan-official | 英雄资料 | 盾山 | https://pvp.qq.com/web201605/herodetail/dunshan.shtml |
| c1-duoliya-official | 英雄资料 | 朵莉亚 | https://pvp.qq.com/web201605/herodetail/duoliya.shtml |
| c1-fei-official | 英雄资料 | 暃 | https://pvp.qq.com/web201605/herodetail/fei.shtml |
| c1-ganjiangmoye-official | 英雄资料 | 干将莫邪 | https://pvp.qq.com/web201605/herodetail/ganjiangmoye.shtml |
| c1-gaojianli-official | 英雄资料 | 高渐离 | https://pvp.qq.com/web201605/herodetail/gaojianli.shtml |
| c1-geya-official | 英雄资料 | 戈娅 | https://pvp.qq.com/web201605/herodetail/geya.shtml |
| c1-gongbenwuzang-official | 英雄资料 | 宫本武藏 | https://pvp.qq.com/web201605/herodetail/gongbenwuzang.shtml |
| c1-gongsunli-official | 英雄资料 | 公孙离 | https://pvp.qq.com/web201605/herodetail/gongsunli.shtml |
| c1-guanyu-official | 英雄资料 | 关羽 | https://pvp.qq.com/web201605/herodetail/guanyu.shtml |
| c1-guiguzi-official | 英雄资料 | 鬼谷子 | https://pvp.qq.com/web201605/herodetail/guiguzi.shtml |
| c1-hainuo-official | 英雄资料 | 海诺 | https://pvp.qq.com/web201605/herodetail/hainuo.shtml |
| c1-haiyue-official | 英雄资料 | 海月 | https://pvp.qq.com/web201605/herodetail/haiyue.shtml |
| c1-hanxin-official | 英雄资料 | 韩信 | https://pvp.qq.com/web201605/herodetail/hanxin.shtml |
| c1-houyi-official | 英雄资料 | 后羿 | https://pvp.qq.com/web201605/herodetail/houyi.shtml |
| c1-huamulan-official | 英雄资料 | 花木兰 | https://pvp.qq.com/web201605/herodetail/huamulan.shtml |
| c1-huangzhong-official | 英雄资料 | 黄忠 | https://pvp.qq.com/web201605/herodetail/huangzhong.shtml |
| c1-jialuo-official | 英雄资料 | 伽罗 | https://pvp.qq.com/web201605/herodetail/jialuo.shtml |
| c1-jiangziya-official | 英雄资料 | 姜子牙 | https://pvp.qq.com/web201605/herodetail/jiangziya.shtml |
| c1-jinchan-official | 英雄资料 | 金蝉 | https://pvp.qq.com/web201605/herodetail/jinchan.shtml |
| c1-jing-official | 英雄资料 | 镜 | https://pvp.qq.com/web201605/herodetail/jing.shtml |
| c1-jixiaoman-official | 英雄资料 | 姬小满 | https://pvp.qq.com/web201605/herodetail/jixiaoman.shtml |
| c1-jvyoujing-official | 英雄资料 | 橘右京 | https://pvp.qq.com/web201605/herodetail/jvyoujing.shtml |
| c1-kai-official | 英雄资料 | 铠 | https://pvp.qq.com/web201605/herodetail/kai.shtml |
| c1-kongkonger-official | 英雄资料 | 空空儿 | https://pvp.qq.com/web201605/herodetail/kongkonger.shtml |
| c1-kuangtie-official | 英雄资料 | 狂铁 | https://pvp.qq.com/web201605/herodetail/kuangtie.shtml |
| c1-laixiao-official | 英雄资料 | 莱西奥 | https://pvp.qq.com/web201605/herodetail/laixiao.shtml |
| c1-lan-official | 英雄资料 | 澜 | https://pvp.qq.com/web201605/herodetail/lan.shtml |
| c1-lanlingwang-official | 英雄资料 | 兰陵王 | https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml |
| c1-laofuzi-official | 英雄资料 | 老夫子 | https://pvp.qq.com/web201605/herodetail/laofuzi.shtml |
| c1-lianpo-official | 英雄资料 | 廉颇 | https://pvp.qq.com/web201605/herodetail/lianpo.shtml |
| c1-libai-official | 英雄资料 | 李白 | https://pvp.qq.com/web201605/herodetail/libai.shtml |
| c1-liubang-official | 英雄资料 | 刘邦 | https://pvp.qq.com/web201605/herodetail/liubang.shtml |
| c1-liubei-official | 英雄资料 | 刘备 | https://pvp.qq.com/web201605/herodetail/liubei.shtml |
| c1-liushan-official | 英雄资料 | 刘禅 | https://pvp.qq.com/web201605/herodetail/liushan.shtml |
| c1-lixin-official | 英雄资料 | 李信 | https://pvp.qq.com/web201605/herodetail/lixin.shtml |
| c1-liyuanfang-official | 英雄资料 | 李元芳 | https://pvp.qq.com/web201605/herodetail/liyuanfang.shtml |
| c1-lubandashi-official | 英雄资料 | 鲁班大师 | https://pvp.qq.com/web201605/herodetail/lubandashi.shtml |
| c1-lubanqihao-official | 英雄资料 | 鲁班七号 | https://pvp.qq.com/web201605/herodetail/lubanqihao.shtml |
| c1-luna-official | 英雄资料 | 露娜 | https://pvp.qq.com/web201605/herodetail/luna.shtml |
| c1-luyana-official | 英雄资料 | 卢雅那 | https://pvp.qq.com/web201605/herodetail/luyana.shtml |
| c1-lvbu-official | 英雄资料 | 吕布 | https://pvp.qq.com/web201605/herodetail/lvbu.shtml |
| c1-machao-official | 英雄资料 | 马超 | https://pvp.qq.com/web201605/herodetail/machao.shtml |
| c1-makeboluo-official | 英雄资料 | 马可波罗 | https://pvp.qq.com/web201605/herodetail/makeboluo.shtml |
| c1-mengqi-official | 英雄资料 | 梦奇 | https://pvp.qq.com/web201605/herodetail/mengqi.shtml |
| c1-mengtian-official | 英雄资料 | 蒙恬 | https://pvp.qq.com/web201605/herodetail/mengtian.shtml |
| c1-mengya-official | 英雄资料 | 蒙犽 | https://pvp.qq.com/web201605/herodetail/mengya.shtml |
| c1-milaidi-official | 英雄资料 | 米莱狄 | https://pvp.qq.com/web201605/herodetail/milaidi.shtml |
| c1-mingshiyin-official | 英雄资料 | 明世隐 | https://pvp.qq.com/web201605/herodetail/mingshiyin.shtml |
| c1-miyue-official | 英雄资料 | 芈月 | https://pvp.qq.com/web201605/herodetail/miyue.shtml |
| c1-mozi-official | 英雄资料 | 墨子 | https://pvp.qq.com/web201605/herodetail/mozi.shtml |
| c1-nakelulu-official | 英雄资料 | 娜可露露 | https://pvp.qq.com/web201605/herodetail/nakelulu.shtml |
| c1-nezha-official | 英雄资料 | 哪吒 | https://pvp.qq.com/web201605/herodetail/nezha.shtml |
| c1-niumo-official | 英雄资料 | 牛魔 | https://pvp.qq.com/web201605/herodetail/niumo.shtml |
| c1-nvwa-official | 英雄资料 | 女娲 | https://pvp.qq.com/web201605/herodetail/nvwa.shtml |
| c1-pangu-official | 英雄资料 | 盘古 | https://pvp.qq.com/web201605/herodetail/pangu.shtml |
| c1-peiqinhu-official | 英雄资料 | 裴擒虎 | https://pvp.qq.com/web201605/herodetail/peiqinhu.shtml |
| c1-sangqi-official | 英雄资料 | 桑启 | https://pvp.qq.com/web201605/herodetail/sangqi.shtml |
| c1-shangguanwaner-official | 英雄资料 | 上官婉儿 | https://pvp.qq.com/web201605/herodetail/shangguanwaner.shtml |
| c1-shaosiyuan-official | 英雄资料 | 少司缘 | https://pvp.qq.com/web201605/herodetail/shaosiyuan.shtml |
| c1-shenmengxi-official | 英雄资料 | 沈梦溪 | https://pvp.qq.com/web201605/herodetail/shenmengxi.shtml |
| c1-sikongzhen-official | 英雄资料 | 司空震 | https://pvp.qq.com/web201605/herodetail/sikongzhen.shtml |
| c1-simayi-official | 英雄资料 | 司马懿 | https://pvp.qq.com/web201605/herodetail/simayi.shtml |
| c1-sulie-official | 英雄资料 | 苏烈 | https://pvp.qq.com/web201605/herodetail/sulie.shtml |
| c1-sunbin-official | 英雄资料 | 孙膑 | https://pvp.qq.com/web201605/herodetail/sunbin.shtml |
| c1-sunce-official | 英雄资料 | 孙策 | https://pvp.qq.com/web201605/herodetail/sunce.shtml |
| c1-sunquan-official | 英雄资料 | 孙权 | https://pvp.qq.com/web201605/herodetail/sunquan.shtml |
| c1-sunshangxiang-official | 英雄资料 | 孙尚香 | https://pvp.qq.com/web201605/herodetail/sunshangxiang.shtml |
| c1-sunwukong-official | 英雄资料 | 孙悟空 | https://pvp.qq.com/web201605/herodetail/sunwukong.shtml |
| c1-taiyizhenren-official | 英雄资料 | 太乙真人 | https://pvp.qq.com/web201605/herodetail/taiyizhenren.shtml |
| c1-wangwei-official | 英雄资料 | 王维 | https://pvp.qq.com/web201605/herodetail/wangwei.shtml |
| c1-wangzhaojun-official | 英雄资料 | 王昭君 | https://pvp.qq.com/web201605/herodetail/wangzhaojun.shtml |
| c1-wuzetian-official | 英雄资料 | 武则天 | https://pvp.qq.com/web201605/herodetail/wuzetian.shtml |
| c1-xiahoudun-official | 英雄资料 | 夏侯惇 | https://pvp.qq.com/web201605/herodetail/xiahoudun.shtml |
| c1-xialuote-official | 英雄资料 | 夏洛特 | https://pvp.qq.com/web201605/herodetail/xialuote.shtml |
| c1-xiangyu-official | 英雄资料 | 项羽 | https://pvp.qq.com/web201605/herodetail/xiangyu.shtml |
| c1-xiaoqiao-official | 英雄资料 | 小乔 | https://pvp.qq.com/web201605/herodetail/xiaoqiao.shtml |
| c1-xinmoliuer-official | 英雄资料 | 心魔六耳 | https://pvp.qq.com/web201605/herodetail/xinmoliuer.shtml |
| c1-xishi-official | 英雄资料 | 西施 | https://pvp.qq.com/web201605/herodetail/xishi.shtml |
| c1-yadianna-official | 英雄资料 | 雅典娜 | https://pvp.qq.com/web201605/herodetail/yadianna.shtml |
| c1-yalian-official | 英雄资料 | 亚连 | https://pvp.qq.com/web201605/herodetail/yalian.shtml |
| c1-yangjian-official | 英雄资料 | 杨戬 | https://pvp.qq.com/web201605/herodetail/yangjian.shtml |
| c1-yangyuhuan-official | 英雄资料 | 杨玉环 | https://pvp.qq.com/web201605/herodetail/yangyuhuan.shtml |
| c1-yao-official | 英雄资料 | 瑶 | https://pvp.qq.com/web201605/herodetail/yao.shtml |
| c1-yase-official | 英雄资料 | 亚瑟 | https://pvp.qq.com/web201605/herodetail/yase.shtml |
| c1-ying-official | 英雄资料 | 影 | https://pvp.qq.com/web201605/herodetail/ying.shtml |
| c1-yingzheng-official | 英雄资料 | 嬴政 | https://pvp.qq.com/web201605/herodetail/yingzheng.shtml |
| c1-yixing-official | 英雄资料 | 弈星 | https://pvp.qq.com/web201605/herodetail/yixing.shtml |
| c1-yuange-official | 英雄资料 | 元歌 | https://pvp.qq.com/web201605/herodetail/yuange.shtml |
| c1-yuanliuzhizi_archer-official | 英雄资料 | 元流之子(射手) | https://pvp.qq.com/web201605/herodetail/yuanliuzhizi_archer.shtml |
| c1-yuanliuzhizi_assassin-official | 英雄资料 | 元流之子(刺客) | https://pvp.qq.com/web201605/herodetail/yuanliuzhizi_assassin.shtml |
| c1-yuanliuzhizi_magic-official | 英雄资料 | 元流之子(法师) | https://pvp.qq.com/web201605/herodetail/yuanliuzhizi_magic.shtml |
| c1-yuanliuzhizi_support-official | 英雄资料 | 元流之子(辅助) | https://pvp.qq.com/web201605/herodetail/yuanliuzhizi_support.shtml |
| c1-yuanliuzhizi_tank-official | 英雄资料 | 元流之子(坦克) | https://pvp.qq.com/web201605/herodetail/yuanliuzhizi_tank.shtml |
| c1-yuji-official | 英雄资料 | 虞姬 | https://pvp.qq.com/web201605/herodetail/yuji.shtml |
| c1-yunying-official | 英雄资料 | 云缨 | https://pvp.qq.com/web201605/herodetail/yunying.shtml |
| c1-yunzhongjun-official | 英雄资料 | 云中君 | https://pvp.qq.com/web201605/herodetail/yunzhongjun.shtml |
| c1-zhangfei-official | 英雄资料 | 张飞 | https://pvp.qq.com/web201605/herodetail/zhangfei.shtml |
| c1-zhangliang-official | 英雄资料 | 张良 | https://pvp.qq.com/web201605/herodetail/zhangliang.shtml |
| c1-zhaohuaizhen-official | 英雄资料 | 赵怀真 | https://pvp.qq.com/web201605/herodetail/zhaohuaizhen.shtml |
| c1-zhaoyun-official | 英雄资料 | 赵云 | https://pvp.qq.com/web201605/herodetail/zhaoyun.shtml |
| c1-zhenji-official | 英雄资料 | 甄姬 | https://pvp.qq.com/web201605/herodetail/zhenji.shtml |
| c1-zhongkui-official | 英雄资料 | 钟馗 | https://pvp.qq.com/web201605/herodetail/zhongkui.shtml |
| c1-zhongwuyan-official | 英雄资料 | 钟无艳 | https://pvp.qq.com/web201605/herodetail/zhongwuyan.shtml |
| c1-zhouyv-official | 英雄资料 | 周瑜 | https://pvp.qq.com/web201605/herodetail/zhouyv.shtml |
| c1-zhuangzhou-official | 英雄资料 | 庄周 | https://pvp.qq.com/web201605/herodetail/zhuangzhou.shtml |
| c1-zhubajie-official | 英雄资料 | 猪八戒 | https://pvp.qq.com/web201605/herodetail/zhubajie.shtml |
| c1-zhugeliang-official | 英雄资料 | 诸葛亮 | https://pvp.qq.com/web201605/herodetail/zhugeliang.shtml |

## 4. 不确定项 / 需重点确认

### 4.1 出装引用了 item.json 中不存在的装备 ID（**对应边未建立**）

| 装备 ID | 被引用次数 | 处理 |
| --- | --- | --- |
| 1223 | 2 | 未建 RECOMMENDS_ITEM 边；未造桩节点（规格书 3.4 要求装备恰 115）|
| 1225 | 1 | 未建 RECOMMENDS_ITEM 边；未造桩节点（规格书 3.4 要求装备恰 115）|
| 1722 | 16 | 未建 RECOMMENDS_ITEM 边；未造桩节点（规格书 3.4 要求装备恰 115）|
| 91040 | 1 | 未建 RECOMMENDS_ITEM 边；未造桩节点（规格书 3.4 要求装备恰 115）|

> 待官方 `item.json` 补齐后可重跑 `build_graph_data.py` + `init_graph.py`。

### 4.2 同一关系被两处官方页面各陈述一次（导入时按唯一键合并）

| 关系（from → to，type） | 出现的页面区块 |
| --- | --- |
| 花木兰 → 墨子（COUNTERS） | 被压制英雄 @ https://pvp.qq.com/web201605/herodetail/mozi.shtml；压制英雄 @ https://pvp.qq.com/web201605/herodetail/huamulan.shtml |
| 兰陵王 → 鲁班七号（COUNTERS） | 被压制英雄 @ https://pvp.qq.com/web201605/herodetail/lubanqihao.shtml；压制英雄 @ https://pvp.qq.com/web201605/herodetail/lanlingwang.shtml |
| 孙膑 → 李白（COUNTERS） | 压制英雄 @ https://pvp.qq.com/web201605/herodetail/sunbin.shtml；被压制英雄 @ https://pvp.qq.com/web201605/herodetail/libai.shtml |
| 王昭君 → 吕布（COUNTERS） | 被压制英雄 @ https://pvp.qq.com/web201605/herodetail/lvbu.shtml；压制英雄 @ https://pvp.qq.com/web201605/herodetail/wangzhaojun.shtml |
| 露娜 → 虞姬（COUNTERS） | 压制英雄 @ https://pvp.qq.com/web201605/herodetail/luna.shtml；被压制英雄 @ https://pvp.qq.com/web201605/herodetail/yuji.shtml |

> 两条陈述事实一致，方向一致；Neo4j 侧 MERGE 唯一键为 `起点+类型+终点+patch`，已合并为 1 条边。语料与图谱不冲突。

### 4.3 与规格书描述不一致、已实测修正的点（详见 DECISIONS.md）

- 铭文 `ming_type`：规格书 6.1b 写有 `green`，**实测仅 red/yellow/blue**，无绿色系。
- 装备 `item_type`：实测取值 {1,2,3,4,5,7}，**不存在 6**；未命中类型落为「未知(N)」。
- 貂蝉详情页存在**两套模板**（旧 `href` / 新 `data-src`），已用双通道提取解决，未放宽断言。

### 4.4 别名清单（供实体链接层审核，每英雄 ≥5）

- 别名语料 `data/hero_aliases.json` 覆盖 **5 个演示英雄**（M1a 已交付、已审）；其余英雄 `aliases` 暂为空列表，待 M2 实体链接层按需补齐（见 DECISIONS.md M1b 条）。

| 英雄 | 别名 |
| --- | --- |
| 貂蝉 | 蝉儿、貂蝉妹妹、貂婵、貂禅、刁蝉、貂蝉小姐姐 |
| 兰陵王 | 兰陵、老兰陵、兰凌王、蓝陵王、兰陵皇、隐身王 |
| 亚瑟 | 亚瑟王、老亚瑟、亚瑟瑟、亚色、亚瑟君、亚瑟大王 |
| 后羿 | 后裔、后弈、老后羿、后羿射日、后一、后羿哥 |
| 东皇太一 | 东皇、太一、东皇太乙、东皇太1、东皇大人、东皇太一神 |
