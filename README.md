# 本地竞价选股器

这个程序把当前目录下三份聚宽策略的选股部分迁移到本地，运行时只读取行情并输出候选股票，不包含下单、持仓、止盈止损和盘后交易统计。

## 运行环境

```powershell
python -m pip install -r requirements.txt
```

当前机器已经安装 `akshare`、`pandas` 和 `numpy`，可以直接试跑。

## 每天运行

在交易日 09:26 之后执行：

```powershell
python .\local_selector.py
```

也可以双击 `run_selector.bat`，或给它追加参数。

指定日期或单个策略：

```powershell
python .\local_selector.py --date 2026-08-17
python .\local_selector.py --strategy 低位首阳必买
python .\local_selector.py --strategy 打板 竞价量比
python .\local_selector.py --refresh
python .\local_selector.py --daily-source sina
python .\local_selector.py --daily-source sina --auction-source sina
```

结果文件：

- `output/picks_YYYYMMDD.csv`
- `output/picks_YYYYMMDD.json`

行情请求会缓存到 `cache/`，同一天重复运行时不会重复下载已经成功获取的数据。

## 三份策略的本地化边界

- `低位首阳必买`：保留基础股票池、首板、量价、5 日波动和竞价量价过滤。
- `竞价量比`：保留昨日强势、极端涨停、5 日波动、连板、近 100 日高位和 C/D/E/F 竞价规则。
- `打板`：保留 MA5/MA10/MA30、多板限制、年涨停次数、换手率、MA5 斜率、3% 高开和一字板过滤。
- 聚宽的概念接口没有本地直接等价物；`打板` 的“三板必须命中热点概念”使用昨日涨停池的“所属行业”做热点代理，并在结果 `notes` 中标注。
- 为控制每日请求量，候选范围默认从昨日涨停池开始收敛。这与原策略“扫描全市场后再过滤”并非完全相同，但更适合本地每日运行，也避免对行情接口造成大量请求。

## 注意事项

1. 必须在竞价结束后运行。东方财富源读取 09:26 前盘前分时的最后一条记录；新浪源读取 09:25~09:26 的实际逐笔成交，取最后成交价、合计成交量，并将股转换成手，成交额按价格乘股数合计。如需忽略历史缓存并重新拉取，使用 `--refresh`。
2. 日线默认先请求东方财富，连续三次失败或返回空数据后，本次运行自动切换新浪。也可通过 `--daily-source sina` 直接使用新浪，或 `--daily-source eastmoney` 只用东方财富。新浪成交量和换手率会转换成原有的手、百分数单位。
3. 输出结果是策略条件的机械筛选，不代表投资建议；原聚宽策略中的买入价格、仓位、卖出和风控逻辑均已移除。

## 接口失败排查

若日志出现 `stock_zh_a_hist` / `RemoteDisconnected('Remote end closed connection without response')`，表示东方财富日线连接被远端或网络链路断开；这不能单凭错误判断为限流。2026-10-16 本机复现时，新浪日线可用，东方财富涨停池可用，盘前分时出现间歇性断连。

建议先执行：

```powershell
python .\local_selector.py --daily-source sina --auction-source sina --verbose
```

先保留 `cache/`，不要用 `--refresh` 反复请求。程序会优先复用成功缓存；新浪同样可能受上游访问限制，请保留默认请求间隔。

`--daily-source sina` 只影响日线，截图中的 `stock_zh_a_hist_pre_min_em` 是另一条竞价接口。竞价现默认也使用 `auto`：东方财富断连、空响应或日期不符后，本次运行切换至新浪逐笔成交；可用 `--auction-source sina` 直接使用新浪，或 `--auction-source eastmoney` 只使用东方财富。2026-10-16 本机已核对新浪 09:25 成交价与当日开盘价一致，按昨日查询会返回不同数据，未来日期返回空。若新浪也未提供指定日的竞价成交，仍会标为数据不完整，不使用 09:30 的成交替代。

本机排查还发现 Clash TUN 正在运行，东方财富域名解析到了 `198.18.*` 虚拟地址；因此没有 HTTP/HTTPS 代理环境变量也不代表请求未经过代理。这只是网络线索，尚不能据此断定 Clash 是断连原因；程序未修改代理设置。

只要本次筛选需要的日线或竞价请求有失败，JSON 中就会写入 `status: "incomplete"` 和 `data_errors`，进程退出码为 `2`，此时 CSV 可能只有部分候选，不能将空结果解释为“没有符合条件的股票”。完整执行的退出码为 `0`，整体执行异常为 `1`。空行情和日期不匹配的竞价响应不会新增成功缓存。
