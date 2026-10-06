(async () => {

    const BASE_URL = "https://adventuras.in";
    const LIMIT = 250;

    window.output = [];

    const progressStartedAt = Date.now();
    window.updateProgress = function (progress) {
        const current = Number(progress.current || 0), total = Number(progress.total || 0);
        const elapsedSeconds = Math.max(0, (Date.now() - progressStartedAt) / 1000);
        const payload = {
            ...progress,
            current,
            total,
            elapsed_seconds: Math.round(elapsedSeconds),
            eta_seconds: current > 0 && total > current ? Math.round((elapsedSeconds / current) * (total - current)) : 0,
            updated_at: new Date().toISOString()
        };
        window.__SCRAPER_PROGRESS__ = payload;
        if (typeof window.updateScraperProgress === "function") {
            try {
                const res = window.updateScraperProgress(payload);
                if (res && typeof res.catch === "function") {
                    res.catch(() => {});
                }
            } catch (_) {}
        }
    };

    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const randomDelay = () => 1200 + Math.floor(Math.random() * 1000);

    let page = 1;
    const limit = window.__PRODUCT_LIMIT__ ? Number(window.__PRODUCT_LIMIT__) : 0;

    while (true) {
        console.log(`Fetching Page ${page}...`);
        window.updateProgress({ stage: "Collecting Products", current: page, total: page + 1 });

        let data = null;
        let success = false;
        for (let attempt = 1; attempt <= 5; attempt++) {
            try {
                const response = await fetch(
                    `${BASE_URL}/products.json?limit=${LIMIT}&page=${page}`
                );

                if (!response.ok) {
                    console.warn(`HTTP ${response.status} on Adventuras Page ${page}, attempt ${attempt}/5`);
                    if (attempt < 5) {
                        const waitMs = attempt * 3000;
                        console.log(`Waiting ${waitMs}ms before retry...`);
                        await sleep(waitMs);
                        continue;
                    }
                    console.error(`HTTP ${response.status} on Page ${page} after 5 attempts`);
                    break;
                }

                data = await response.json();
                success = true;
                break;
            } catch (fetchErr) {
                console.warn(`Network error on Adventuras Page ${page}, attempt ${attempt}/5:`, fetchErr);
                if (attempt < 5) {
                    const waitMs = attempt * 3000;
                    await sleep(waitMs);
                    continue;
                }
                console.error(`Persistent network error on Page ${page}:`, fetchErr);
                break;
            }
        }

        if (!success || !data) {
            console.error(`Stopping Adventuras pagination at page ${page} due to persistent error.`);
            break;
        }

        if (!data.products || data.products.length === 0) {
            console.log(`Page ${page} returned no products. Finished pagination.`);
            break;
        }

        let pageColumbiaCount = 0;
        let limitReached = false;
        for (const product of data.products) {
            if (
                !product.vendor ||
                product.vendor.trim().toLowerCase() !== "columbia"
            ) {
                continue;
            }

            pageColumbiaCount++;
            for (const variant of (product.variants || [])) {
                window.output.push({
                    source: "adventuras",
                    product_id: String(product.id),
                    sku: variant.sku || "",
                    ean: variant.barcode || "",
                    title: product.title,
                    price: Number(variant.price),
                    mrp:
                        variant.compare_at_price
                            ? Number(variant.compare_at_price)
                            : Number(variant.price),
                    image_url:
                        product.images?.[0]?.src || "",
                    url:
                        `${BASE_URL}/products/${product.handle}`
                });
                if (limit > 0 && window.output.length >= limit) {
                    limitReached = true;
                    break;
                }
            }
            if (limitReached) {
                break;
            }
        }

        console.log(
            `Page ${page}: ${data.products.length} products (${pageColumbiaCount} Columbia). Total SKUs so far: ${window.output.length}`
        );

        if (limitReached) {
            console.log(`Product limit ${limit} reached. Stopping pagination.`);
            break;
        }

        if (data.products.length < LIMIT) {
            console.log(`Page ${page} returned less than ${LIMIT} products. Finished pagination.`);
            break;
        }

        page++;
        await sleep(randomDelay());
    }

    const totalPages = Math.max(1, page);
    console.log(
        `Collected ${window.output.length} products across ${totalPages} pages`
    );

    console.log("--------------------------------");
    console.log("SCRAPING COMPLETE");
    console.log("--------------------------------");
   
    console.log("Total SKUs :", window.output.length);
  
    console.log("--------------------------------");
    window.updateProgress({ stage: "Completed", current: totalPages, total: totalPages });

    const output = {
        schema_version: 1,
        source: "adventuras",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        products: window.output,
        total_products: window.output.length
    };

    window.scraperResult = output;
    window.__SCRAPER_DONE__ = true;

    if (typeof window.__IS_PLAYWRIGHT__ === "undefined") {
        const blob = new Blob([JSON.stringify(output, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "adventuras_products.json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        console.log("Download Complete!");
        setTimeout(() => { try { window.close(); } catch (_) {} }, 1500);
    } else {
        console.log("Playwright detected: result stored on window.scraperResult");
    }

})();
