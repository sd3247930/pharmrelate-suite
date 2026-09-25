uni.addInterceptor({
	returnValue(res) {
		if (!(!!res && (typeof res === 'object' || typeof res === 'function') && typeof res.then === 'function')) {
			return res
		}
		return new Promise((resolve, reject) => {
			res[0] = (result) => {
				if (result && result[0] === 0) {
					resolve(result[1])
				} else {
					reject(result[1])
				}
			}
		})
	}
})
