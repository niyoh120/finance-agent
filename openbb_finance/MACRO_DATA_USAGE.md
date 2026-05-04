# OpenBB Finance 宏观数据接口使用指南

## 概述

openbb-finance 现已支持中国宏观经济数据，通过 AKShare 数据源提供高质量的本土数据。

## 支持的指标

| 指标 | 说明 | 数据源 |
|------|------|--------|
| GDP | 国内生产总值绝对值 | AKShare |
| GDP_YOY | 国内生产总值年率 | AKShare |
| CPI | 消费者价格指数 | AKShare |
| CPI_YOY | 消费者价格指数年率 | AKShare |
| PPI | 生产者价格指数 | AKShare |
| PMI | 采购经理人指数 | AKShare |

## 使用示例

### 获取中国 GDP 年率数据

```python
from openbb import obb

# 获取中国 GDP 年率数据
data = obb.economy.indicators(symbol="GDP_YOY", country="china", provider="finance")
print(data.to_dataframe())
```

### 获取中国 CPI 年率数据

```python
from openbb import obb

# 获取中国 CPI 年率数据
data = obb.economy.indicators(symbol="CPI_YOY", country="china", provider="finance")
print(data.to_dataframe())
```

### 获取中国 PMI 数据

```python
from openbb import obb

# 获取中国 PMI 数据
data = obb.economy.indicators(symbol="PMI", country="china", provider="finance")
print(data.to_dataframe())
```

### 获取中国 PPI 数据

```python
from openbb import obb

# 获取中国 PPI 数据
data = obb.economy.indicators(symbol="PPI", country="china", provider="finance")
print(data.to_dataframe())
```

## 国家代码支持

对于中国数据，支持以下国家代码变体：
- `china`
- `CN`
- `中国`
- `Chinese`

## 数据字段说明

### 经济指标数据字段

| 字段 | 说明 |
|------|------|
| date | 日期 |
| symbol | 指标符号 |
| symbol_root | 指标根符号 |
| country | 国家 |
| value | 数值 |
| consensus | 预测值（如有） |
| previous | 前值（如有） |
| source | 数据源 |

## 注意事项

1. 中国宏观数据来自 AKShare，确保已安装 `akshare>=1.18.23`
2. 国际宏观数据会尝试使用 OpenBB 内置数据源（OECD、IMF 等）
3. 数据更新频率取决于 AKShare 数据源的更新周期

## 完整示例

```python
from openbb import obb

# 查看最近的中国 GDP 年率数据
gdp_data = obb.economy.indicators(
    symbol="GDP_YOY",
    country="china",
    provider="finance"
)

# 转换为 DataFrame
df = gdp_data.to_dataframe()

# 显示最近 5 条记录
print(df.tail(5))
```
