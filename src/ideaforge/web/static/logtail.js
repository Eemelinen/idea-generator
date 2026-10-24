// Live log tail of the job page (IF-607): polls /jobs/<id>/log with the byte offset it got last
// and appends only the new text; reloads the page once the job has finished. No dependencies.
;(function () {
  const log = document.getElementById('log')
  if (!log || log.dataset.done === 'true') return
  let offset = Number(log.dataset.offset) || 0
  const url = log.dataset.url

  async function poll() {
    try {
      const response = await fetch(`${url}?offset=${offset}`, { cache: 'no-store' })
      if (response.ok) {
        const data = await response.json()
        if (data.text) {
          const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 4
          log.append(document.createTextNode(data.text))
          if (atBottom) log.scrollTop = log.scrollHeight
        }
        offset = data.offset
        if (data.done) {
          window.location.reload()
          return
        }
      }
    } catch (error) {
      // the server is restarting; try again on the next tick
    }
    window.setTimeout(poll, 2000)
  }

  window.setTimeout(poll, 2000)
})()
