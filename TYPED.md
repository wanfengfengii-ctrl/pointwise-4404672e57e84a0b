# 离线类型口径采集

## 已有能力与本次交付

README.md描述的Collector、普通XBRL支持子集、样例、错误类、原CLI及全部原测试继续有效。当前schemaRef只作声明，未提供类型解析。新增Collector.ingest_typed(document_id, xml_bytes, schemas)，返回固定成果ID；schemas是绝对URI字符串到原始XSD bytes的离线映射，禁止联网。保留ingest_xbrl的原语义、成果ID、读取值和导出结构；已有普通成果仍可读取。本次不做完整XSD、远程下载、内联事实、维度或旧成果自动重算。

本题共同结果是：准备侧按离线类型解释事实，归档及消费侧固定并核对同一次解释依据。不能只增加schemaRef参数，也不能仅保存分类体系摘要而继续按unitRef推断类型。可以全量解析、全量校验及重开时全量重新求值，没有增量或扫描次数要求。内部表示、表结构及类型求值组织自行设计。

## 离线文件与声明

typed实例沿用普通XML结构，但必须恰有一个根下schemaRef；其xlink:href是绝对URI。URI逐字符串比较，不解析别名、不规范化、不访问网络。由schemaRef递归跟随xs:import的schemaLocation得到可达文件集；无关映射项完全忽略，不解析、不保存、不影响重投身份。需要的文件缺失或不是非空bytes则拒绝。

XSD命名空间为http://www.w3.org/2001/XMLSchema。仅接受以下结构；命名空间声明不计入属性，容器中只允许XML空白，叶子不得有子元素。DTD、实体声明沿用原拒绝规则。
- xs:schema：唯一普通属性targetNamespace，必须非空；子元素仅为import、具名simpleType、全局element，声明顺序任意。
- xs:import：恰有namespace、schemaLocation属性，无正文；两者非空，schemaLocation必须为绝对URI，目标文件targetNamespace须等于namespace。
- xs:simpleType：仅name属性，名称为NCName；恰有一个xs:restriction子元素。
- xs:restriction：仅base属性，base为QName；子元素仅为下述支持的facet。
- xs:element：仅name及type属性，无正文；name为NCName，type为QName，声明一个可用事实概念。
- facet：仅value属性，无正文。每个restriction的minInclusive、maxInclusive、whiteSpace至多各一个；enumeration可出现多次，同值合并，不受子元素排列顺序影响。

类型与概念各有独立的展开名符号空间；同类展开名重复即拒绝，包括不同可达文件中的重复。QName使用属性所在元素的作用域，无前缀时使用该处默认命名空间，不默认为targetNamespace。类型仅可引用xs:decimal、xs:string或可达文件内的具名simpleType，允许前向依赖。所有可达声明均须合法，即使未被事实使用；缺类型、import文件环或类型继承环均拒绝。不支持include、匿名类型、complexType、list、union、annotation及其他结构或属性。

## 有效值域

xs:decimal基础值域为全部V1可解析的有限十进制，支持minInclusive、maxInclusive和enumeration；不支持decimal上的whiteSpace声明。facet十进制沿用V1词法，不经float、不舍入。缺省继承父界；显式下界不得小于已有父下界，显式上界不得大于已有父上界，即使已有枚举也不得放宽界。新界截取父值域。若本层有枚举，先按精确十进制值去重，每项必须在新界内且属于父值域；否则继承父枚举并按新界筛选。无父枚举且本层无枚举表示不限定枚举。上下界倒置或有效枚举为空均拒绝。

xs:string基础whiteSpace为preserve，支持whiteSpace和enumeration，不支持数值界。whiteSpace仅preserve或collapse，缺省继承；collapse不得退回preserve。collapse仅把XML空白字符空格、TAB、CR、LF替成空格、合并连续空格并去首尾空格，不处理NBSP。枚举按本类型有效whiteSpace处理，每个新枚举值必须属于父类型值域；缺省继承父枚举。继承的枚举值不因子类型改用collapse而改写，仅保留已经是collapse规范形式的值；若因此值域为空须拒绝。例如父preserve枚举仅有' A  B '，子改collapse且无枚举，则拒绝；父collapse、子枚举' A  B '的有效值为'A B'。

每个事实必须有全局概念声明。概念类型决定numeric或text：decimal必须有unitRef，string不得有unitRef，包括nil事实；其余资源、decimals、nil及数值词法沿用V1。nil不作值域比较，但不能含非XML空白正文。typed文本读值采用有效whiteSpace规则；数值保留V1的精确表示、尾随零及负零。SingleElementSource仍保留原路径、展开概念和XML解析后的原文本，不用规范值覆盖来源；普通V1文本仍保持原空白。

## 身份、提交和核账

成功成果固定原实例及全部可达XSD文件的URI、原字节、SHA-256、概念声明类型与有效限制，重开后不依赖调用方schemas。typed成果ID须确定性绑定document_id、原实例和可达文件集，并与V1身份域隔离；具体编码自行设计。receipt.digest及export的原digest仍为实例原字节SHA-256。

同document_id仅当接纳模式、实例及可达文件逐字节相同才是重投，否则抛DocumentConflictError。文件映射顺序无关；可达文件只改空白也冲突，无关项变化仍重投。对于能完成文件结构和import闭包解析的提交，已有身份比较先于类型求值及事实值域校验：同ID换成上界10的可解析包应冲突，新ID则按新口径校验并拒绝12.3。无法取得闭包仍为BusinessValidationError。V1与typed相互提交同一document_id均不得冒充重投。

原实例、类型依据、资源、事实、来源证据、成果及回执一起原子发布。解析、类型或事实校验失败抛BusinessValidationError；数据库异常原样传播。任何失败不得产生部分成果或改变旧成果，失败的新document_id可修正后重试。复用原事务和并发重投边界，不新增后台任务或跨进程采集协议。初始化不得清库、补造损坏证据或改变旧成果含义。

read_facts的调用及FactView字段不变，返回typed的规范值。读取、重投及export均须核账：类型依据的文件摘要、可达集合、成果身份、概念类型与有效限制，以及事实规范值和原来源须相符；缺失或矛盾抛IntegrityError，不能静默改用当前文件或补造证据。允许用持久原文件重新求值，也允许核对持久有效限制，不能依赖调用方文件。V1原有核账与导出不变。

## typed导出

export_evidence对typed成果在原顶层字段之外增加type_basis；原facts字段仍按V1结构输出，value为上述typed规范值，source.raw_text为原文本。type_basis固定为：
- root_uri：schemaRef的URI。
- schemas：按uri排序的列表，每项为uri、sha256、body_base64；body_base64为原文件bytes的标准Base64字符串。
- concepts：所有可达全局概念按concept排序的列表，每项包含concept、type、primitive、white_space、min_inclusive、max_inclusive、enumeration。前三项为展开QName，type为概念直接声明的类型，primitive为xs:decimal或xs:string；decimal的white_space固定为collapse，string为实际模式。无界及不适用的界为null；不限定枚举为null，否则为非空去重列表。string枚举按Unicode码点排序；decimal枚举按数值排序，其界和枚举使用无指数、无多余小数尾零、零写作0的字符串。事实自身的数值表示不做这种规范化。
证据中的文件必须恰为可达集合，不得夹带无关文件。成功导出可JSON序列化且确定性；普通成果不增加type_basis。

## 样例与运行

typed_scenarios.py含手写的两文件分类体系、实例和预期，不包含类型解析器或归档实现。运行：
    python3.11 -B typed_scenarios.py materials
仅检查材料语法与原普通采集样例；它不代表新增能力通过。

实现后运行：
    python3.11 -B typed_scenarios.py verify
    python3.11 -B typed_scenarios.py demo
verify实际核对12.3与枚举12.30相等、collapse值与原证据分离、继承限制拒绝、作用域、换包冲突、无关项重投、V1隔离、事务回滚及重开后证据；失败退出非零。demo展示原口径成果、收紧口径的拒绝和重开后的固定证据。可增加自己的公开契约回归，不修改或删除原测试。

保留.pointwise-runtime.json现有格式：version为1、kind为cli、setup为argv数组列表，verify和demo各为单个argv数组。完成后将原intake verify接上全部原回归与typed联合核验，将原intake demo接上普通样例与本次真实类型口径演示；运行清单继续指向这两个实际入口。交付简短说明，解释类型规范值、原来源和固定依据的归属。
