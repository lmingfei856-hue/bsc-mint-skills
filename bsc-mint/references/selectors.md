# 已知函数选择器

选择器是函数签名 keccak-256 的前 4 字节。脚本用 `bsclib.selector()` 现算，
下面这份表只做核对用，运行时以现算值为准。

## 代币标准函数

- totalSupply()：18160ddd
- decimals()：313ce567
- symbol()：95d89b41
- name()：06fdde03
- balanceOf(address)：70a08231
- transfer(address,uint256)：a9059cbb

## 铸造类函数

- totalMinted()：a2309ff8，KOMA、BROCCOLI、BABYDOGE 的销售合约都响应这个选择器
- token()：fc0c546a，销售合约返回代币地址，AKITA 的 mint 合约响应这个选择器
- mintedByWallet(address)：0d758111，BROCCOLI 的销售合约响应这个选择器

## BROCCOLI 的两个 mint 选择器

- 免费铸造：c4310955，站内 JS 里叫 mintFree，但它对不上 mintFree()、mintFree(address)、mintFree(uint256) 这些常见签名的现算值，实际签名未知，历史库里按原始选择器存，不硬猜签名
- 付费铸造：86355f49，站内 JS 里叫 mint，同样对不上 mint(uint256)、mint(uint256,address) 的现算值，实际签名未知，按原始选择器存

## 模拟时怎么试

- 免费类先按只有选择器本身调一次，再按选择器加 32 字节零参数调一次，值都是 0。
- 付费类先按只有选择器本身调一次，再按选择器加 uint256(1) 调一次，值是每份价格。
- 付费模拟的调用方先用销售合约自己，再用公开的 PancakeSwap V2 Router 地址，都只是 eth_call 静态调用。

## 候选价格和状态函数

脚本在销售合约上逐个试 `bsclib.PRICE_CANDIDATES` 和 `bsclib.STATE_CANDIDATES` 里的签名，
哪个返回了合理数字就用哪个。价格合理范围是每份 0.0001 到 0.1 BNB。
没有哪个响应时，价格以站内配置为准，链上价格写未知。
