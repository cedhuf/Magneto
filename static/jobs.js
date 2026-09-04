/* A download is started, then waited on. Both reading pages wait the same way,
   so they wait with the same code. */
function waitForFile(jobId) {
  return new Promise((resolve, reject) => {
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`/api/status/${jobId}`);
        const data = await res.json();
        if (data.status === 'done') { clearInterval(poll); resolve(data); }
        else if (data.status === 'error') { clearInterval(poll); reject(new Error(data.error)); }
      } catch (e) { clearInterval(poll); reject(e); }
    }, 1000);
  });
}
