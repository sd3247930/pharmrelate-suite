<script>
import { ensureDefaults, getServer } from './services/store'

export default {
	onLaunch() {
		// 首次启动写入默认配置，避免用户在设置页面对空值
		ensureDefaults()
		const server = getServer()
		console.log('[籽关通] 服务地址：', server.baseUrl || '（未设置）')
	}
}
</script>

<style>
page {
	background-color: #f1f4f6;
	color: #101a22;
	font-size: 14px;
	line-height: 1.5;
}

/* 状态一律"颜色 + 文字"双重表达，颜色不作为唯一信息载体 */
.badge {
	display: inline-block;
	padding: 2px 10px;
	border-radius: 999px;
	font-size: 12px;
	border: 1px solid;
}

.badge-ok {
	color: #15803d;
	background: #e6f4ea;
	border-color: #a8d5b5;
}

.badge-warn {
	color: #b45309;
	background: #fdf3e5;
	border-color: #f0cfa0;
}

.badge-error {
	color: #b91c1c;
	background: #fdeaea;
	border-color: #f0b4b4;
}

.badge-info {
	color: #1d4ed8;
	background: #e9eefc;
	border-color: #b9c8f2;
}

.badge-neutral {
	color: #475569;
	background: #eef1f4;
	border-color: #d3dae0;
}

.code {
	font-family: Consolas, Menlo, monospace;
	/* 20 位追溯码在窄屏上折行，不被裁切 */
	word-break: break-all;
	word-wrap: break-word;
}
</style>
