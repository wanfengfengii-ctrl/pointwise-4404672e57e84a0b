# 研报资料中心：普通 XBRL 采集归档

Python 3.11 标准库实现，供采集员接纳供应方的离线普通 XBRL 文件，研究员读取固定成果并核对来源。不需要安装依赖。命令从项目根目录运行。

## 一天的工作

1. 接收非空 document_id 与原始 bytes，创建内存接纳尝试。
2. 计算原字节 SHA-256，核对成功身份；同 ID 同字节重投返回原成果，不同字节冲突。
3. 解析 XML，保留逐元素命名空间作用域；构造本文件主体、期间与单位目录。
4. 按根下普通叶子事实的出现顺序分配从 1 开始的序号，保留原文本和单元素路径。
5. 直接从十进制字符串构造 Decimal，区分 nil、空文本及零，保存 decimals 元数据。
6. 校验完整候选批次的资源、身份、值与来源；失败的新标识仍可修正后重试。
7. 同一 SQLite 事务发布原文、资源、事实、证据、成果和回执；失败撤销全部新增记录。
8. 研究员按固定成果读取、按概念及报告期间取交集、核账及导出证据；重开后结果相同。

## 使用

完整原回归及确定性子场景：

    python3.11 -B -m unittest discover -s tests -t . -v
    python3.11 -B -m xcollect.documents.intake verify

实际演示使用测试临时目录创建归档，接纳 samples/ordinary.xml、精确重投、关闭重开、与手写 samples/expected.json 比较并输出证据：

    python3.11 -B -m xcollect.documents.intake demo

手动操作（archive.sqlite 是当前项目内显式指定的业务数据库；不自动装载样例）：

    python3.11 -B -m xcollect.documents.intake ingest --db archive.sqlite --document-id report-2025 --file samples/ordinary.xml

返回固定成果 ID。将返回 ID 用作以下命令的 --result-id 参数：

    python3.11 -B -m xcollect.documents.intake export --db archive.sqlite --result-id RESULT_ID
    python3.11 -B -m xcollect.documents.intake read --db archive.sqlite --result-id RESULT_ID

业务异常或数据库异常使命令失败并保留原异常；argparse 参数错误退出 2，verify 测试失败退出 1，成功退出 0。

## Python API

    from xcollect.documents.intake import Collector
    with Collector("archive.sqlite") as c:
        result_id = c.ingest_xbrl("report-2025", xml_bytes)
        receipt = c.receipt("report-2025")
        facts = c.read_facts(result_id, "{urn:report}Revenue",
                             ("duration", "2025-01-01", "2025-12-31"))
        evidence = c.export_evidence(result_id)

Collector 默认为 :memory:；显式路径的父目录须存在。不同线程各自创建 Collector；公开调用按该连接顺序执行。SQLite 写事务再次核对来源身份，并发同字节成功接纳只产生一份成果；数据库锁错误如实传播，可重新提交。同 ID 实际字节一致才是重投；同字节新 ID 建立独立成果。成果 ID 为版本域、UTF-8 标识长度、标识与源摘要的 SHA-256，不依赖时钟或随机值。

receipt 返回不可变 Receipt(document_id, result_id, digest, fact_count)，未知返回 None。read_facts 返回按原序排列的 FactView 元组，包含 Decimal/str/None、nil、decimals、Context 与 Unit。概念为展开 QName；期间为 ('instant', YYYY-MM-DD) 或 ('duration', 起日, 止日)。两个筛选同时指定时取交集，无命中返回空元组。export_evidence 返回 JSON 兼容字典：document_id、result_id、digest、fact_count、facts；数值使用无损定点字符串。

BusinessValidationError 表示提交内容不符合子集；DocumentConflictError 表示已接纳身份冲突；NotFound 表示未知成果；IntegrityError 表示归档核账失败；非法查询参数为 ValueError，且先于成果查找校验。数据库异常不包装为业务校验错误。

## 支持子集与口径

根必须为 XBRL instance 命名空间的 xbrl。DTD、实体声明和内联 XBRL 拒绝；XML 内建字符引用正常解码。schemaRef 仅支持空的 link:schemaRef，必须带 xlink:type="simple" 和 xlink:href；该声明不会触发联网或解析。

context 仅有 entity/identifier（非空文本和 scheme）及 period，顺序固定；period 支持有效日历日期 instant 或 startDate/endDate，保留类型及完整端点，起日不得晚于止日。不支持 segment、scenario、维度或 forever。context/unit 的非空 id 在整个文档资源集合中唯一，引用严格限定本文件。

unit 可为一个或多个 measure，或单个 divide，其 unitNumerator/unitDenominator 均含非空 measure 列表。QName 按 measure 本身的命名空间作用域解释；顺序、重复度及商的方向保持，不约分、不换算。

普通事实仅为根下带 contextRef 的非基础设施叶子元素，不支持元组或后代标记。概念使用展开 QName。带 unitRef 为数值，否则为文本。允许属性 contextRef、unitRef、decimals、xsi:nil、id、xml:lang；id/xml:lang 仅接纳为原文属性，不作为读取身份或语言转换规则。文本保持 XML 解析后的空白，证据不是原字节切片。

数值去除首尾 XML 空白后接受带可选符号的十进制，不接受指数、千分位和非有限值；不经 float、不舍入。decimals 可缺省、INF 或整数，仅作元数据；precision、sign、scale、format 等不支持。nil 仅接受 true/1/false/0；nil=true 只允许空或 XML 空白，值为 None。非 nil 空数值拒绝，空文本为 ''，数值 0 为 Decimal。尾随零与负零表示在读取及导出保留。

每条事实保存一个 SingleElementSource(path, concept, raw_text)。path 从根 (1,) 开始，元素子节点从 1 计数；普通事实路径如 (1, 10)，不依赖前缀别名。发布前重新定位并比较候选，归档后读取持久记录，不重新解析 XML。没有多片来源接口。

## 模块与持久边界

 documents 的 intake、identity、storage、xml、dispatch 接收并保全来源；resources 的 names、periods、contexts、units、catalog 解释本文件资源；facts 的 extract、numeric、candidates、validation 交付可发布的普通事实；archive 的 schema、repository、publish、receipts 拥有事务和固定成果；archive/evidence 与 consumption 的 reconcile、select、read、export 消费持久成果。errors 提供统一错误词汇。

SQLite 启用外键与唯一约束，七张业务表共同提交。重复初始化只验证版本和表结构，不清库、不重新导入样例，不修复已有损坏。不兼容库明确失败。固定成果无修改 API；用户应通过新 document_id 接纳修正文件。越过 API 直接修改数据库不受写入契约保护；可检测的源摘要、固定身份、计数、资源关联、值与证据破坏使读取和导出失败，不猜测补造。

samples/expected.json 是独立列出的手算记录：文本、12.30、nil、空文本、零、nil 数值、2.500，三个期间主体，简单/除法/反向/重复单位。测试还覆盖前缀遮蔽、大十进制、非法末事实、缺引用、并发重投、多成果隔离、真实 SQLite 触发器导致的事务回滚、隔离副本损坏与重复初始化。预期不调用生产解析函数生成。测试及 demo 使用项目文件或自身临时目录，不访问外部来源。
