(async () => {

    // --------------------------------------------------
    // Helpers
    // --------------------------------------------------

    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

    const randomDelay = () =>
        typeof window.__PAGE_DELAY__ !== "undefined"
            ? window.__PAGE_DELAY__
            : 300;


    // --------------------------------------------------
    // Config
    // --------------------------------------------------

    const PAGE_SIZE = 40;

    const CONCURRENCY =
        typeof window.__CONCURRENCY__ !== "undefined"
            ? window.__CONCURRENCY__
            : 7;
    const progressStartedAt = Date.now();
    window.updateProgress = function (progress) {
        const current = Number(progress.current || 0), total = Number(progress.total || 0);
        const elapsedSeconds = Math.max(0, (Date.now() - progressStartedAt) / 1000);
        const payload = { ...progress, current, total, elapsed_seconds: Math.round(elapsedSeconds),
            eta_seconds: current > 0 && total > current ? Math.round((elapsedSeconds / current) * (total - current)) : 0,
            updated_at: new Date().toISOString() };
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

    const BASE_URL =
        "https://searchbff.tatacliq.com/products/mpl/search";

    const MCVID =
        "17842193248194609071977202052631231983";

    const DETAIL_URL = productId =>
        `https://www.tatacliq.com/marketplacewebservices/v2/mpl/products/productDetails/${productId.toLowerCase()}?isPwa=true&isMDE=true&isDynamicVar=true`;


    // --------------------------------------------------
    // Build Search URL
    // --------------------------------------------------

    function buildUrl(page) {

        const params = new URLSearchParams({

            searchText:
                "columbia:relevance:inStockFlag:true",

            isKeywordRedirect: "false",

            isKeywordRedirectEnabled: "false",

            channel: "WEB",

            isMDE: "true",

            isTextSearch: "false",

            isFilter: "false",

            qc: "false",

            test:
                "invizbff.qpsv3-inviz.ab",

            page: String(page),

            mcvid: MCVID,

            customerId: "",

            isSuggested: "false",

            isFilterDataRequired: "true",

            isPwa: "true",

            pageSize: String(PAGE_SIZE),

            typeID: "all"

        });

        return `${BASE_URL}?${params.toString()}`;

    }


    // --------------------------------------------------
    // Fetch Listing Page
    // --------------------------------------------------

    async function fetchPage(page) {

        const res = await fetch(buildUrl(page), {

            headers: {

                Accept: "application/json"

            }

        });

        if (!res.ok)
            throw new Error(`HTTP ${res.status}`);

        return await res.json();

    }


    // --------------------------------------------------
    // Fetch Variant Information
    // --------------------------------------------------
    // Variant Fetching (Low Memory / Direct Stream)
    // --------------------------------------------------

    async function fetchVariants(productId) {
        if (!productId) return [];
        const normalizedId = String(productId).trim();
        const url = DETAIL_URL(normalizedId);

        // Fetch with a 5-second abort timeout so hanging server sockets never freeze workers
        for (let attempt = 1; attempt <= 2; attempt++) {
            let controller = null;
            let timeoutId = null;

            try {
                controller = new AbortController();
                timeoutId = setTimeout(() => controller.abort(), 5000);

                const res = await fetch(url, {
                    headers: {
                        Accept: "application/json"
                    },
                    signal: controller.signal
                });

                clearTimeout(timeoutId);

                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }

                const data = await res.json();
                const rawVariants = data.variantOptions || [];

                return rawVariants.map(v => ({
                    size:
                        v.sizelink?.size ||
                        v.sizelink?.brandSize ||
                        "",
                    sku:
                        v.sizelink?.productCode ||
                        "",
                    available:
                        !!v.sizelink?.isAvailable,
                    stock:
                        Number(
                            v.sizelink?.stockCount ?? 0
                        ) || 0,
                    url:
                        v.sizelink?.url
                            ? "https://www.tatacliq.com" +
                              v.sizelink.url
                            : ""
                }));

            } catch (err) {
                if (timeoutId) clearTimeout(timeoutId);

                if (attempt === 1) {
                    await sleep(200);
                } else {
                    console.warn(
                        `Variant fetch failed for ${normalizedId}: ${err.message}`
                    );
                }
            }
        }

        return [];
    }


    // --------------------------------------------------
    // Product Storage
    // --------------------------------------------------

    // --------------------------------------------------
    // Product Storage & Listing Checkpoint Buffer
    // --------------------------------------------------

    const cleanProducts = [];
    const seenProductIds = new Set();
    window.__TATA_UNSAVED_LISTINGS__ = window.__TATA_UNSAVED_LISTINGS__ || [];
    window.drainUnsavedListings = function () {
        const u = window.__TATA_UNSAVED_LISTINGS__ || [];
        window.__TATA_UNSAVED_LISTINGS__ = [];
        return u;
    };

    function processProducts(products, pageNumber = 0) {
        if (!Array.isArray(products)) return [];
        const scrapedAt = new Date().toISOString();

        const priceValue = value =>
            Number(
                value?.value ??
                value?.rawValue ??
                String(
                    value?.formattedValue || ""
                ).replace(/[^0-9.]/g, "")
            ) || 0;

        const newItemsThisPage = [];

        for (const p of products) {
            const pid = String(p.productId || "").trim();
            if (!pid) continue;

            // Deduplicate products across page boundaries
            if (seenProductIds.has(pid)) {
                continue;
            }
            seenProductIds.add(pid);

            const item = {
                source: "tatacliq",
                product_id: pid,
                sku: "",
                ean: "",
                available: !!p.inStockFlag,
                title: p.productname || "",
                price: priceValue(p.price?.sellingPrice),
                mrp: priceValue(p.price?.mrpPrice) || priceValue(p.price?.sellingPrice),
                image_url: p.imageURL
                    ? (p.imageURL.startsWith("http") ? p.imageURL : "https:" + p.imageURL)
                    : "",
                url: p.webURL ? "https://www.tatacliq.com" + p.webURL : "",
                variants: [],
                scraped_at: scrapedAt
            };

            cleanProducts.push(item);
            newItemsThisPage.push(item);
        }

        if (newItemsThisPage.length > 0) {
            window.__TATA_UNSAVED_LISTINGS__.push({
                page: pageNumber,
                products: newItemsThisPage
            });
            window.__TATA_LAST_LISTING_PAGE__ = pageNumber;
        }

        return newItemsThisPage;
    }

    // --------------------------------------------------
    // Fetch Listing Pages (Phase 1)
    // --------------------------------------------------

    const hasInitialProducts = Array.isArray(window.__INITIAL_PRODUCTS__) && window.__INITIAL_PRODUCTS__.length > 0;

    if (hasInitialProducts) {
        console.log(`[TATA RESUME] Phase 1 already complete: Loaded ${window.__INITIAL_PRODUCTS__.length} listing products from database checkpoint.`);
        for (const p of window.__INITIAL_PRODUCTS__) {
            const pid = String(p.product_id || p.productId || "").trim();
            if (pid && !seenProductIds.has(pid)) {
                seenProductIds.add(pid);
                cleanProducts.push({
                    source: "tatacliq",
                    product_id: pid,
                    sku: p.sku || "",
                    ean: p.ean || "",
                    available: p.available !== undefined ? Boolean(p.available) : true,
                    title: p.title || p.productname || "",
                    price: Number(p.price || 0),
                    mrp: Number(p.mrp || p.price || 0),
                    image_url: p.image_url || p.imageURL || "",
                    url: p.url || (p.webURL ? "https://www.tatacliq.com" + p.webURL : ""),
                    variants: Array.isArray(p.variants) ? p.variants : [],
                    scraped_at: p.scraped_at || new Date().toISOString()
                });
            }
        }
        updateProgress({ stage: "Listing Phase Complete", current: cleanProducts.length, total: cleanProducts.length });
    } else {
        const startPage = typeof window.__START_PAGE__ !== "undefined" ? Number(window.__START_PAGE__) : 0;
        console.log(`Fetching listing pages (Starting from page ${startPage})...`);

        let totalPages = 1;
        if (startPage === 0) {
            const first = await fetchPage(0);
            totalPages = first.pagination?.totalPages || 1;
            const totalResults = first.pagination?.totalResults || 0;
            console.log(`Found ${totalPages} pages | ${totalResults} products`);
            processProducts(first.searchresult, 0);
            updateProgress({ stage: "Collecting Products", current: 1, total: totalPages });
            console.log(`Collected ${cleanProducts.length} products`);
        } else {
            // Probe total pages
            try {
                const probe = await fetchPage(0);
                totalPages = probe.pagination?.totalPages || 1;
            } catch (_) {
                totalPages = startPage + 20;
            }
        }

        const loopStart = Math.max(1, startPage);
        for (let page = loopStart; page < totalPages; page++) {
            if (typeof window.__PRODUCT_LIMIT__ !== "undefined" && window.__PRODUCT_LIMIT__ > 0 && cleanProducts.length >= window.__PRODUCT_LIMIT__) {
                console.log(`[TEST MODE] Reached product limit ${window.__PRODUCT_LIMIT__}, stopping listing pagination.`);
                break;
            }

            let success = false;
            for (let attempt = 1; attempt <= 3; attempt++) {
                try {
                    console.log(`Listing Page ${page + 1}/${totalPages} (Attempt ${attempt})`);
                    const data = await fetchPage(page);
                    processProducts(data.searchresult, page);
                    updateProgress({ stage: "Collecting Products", current: page + 1, total: totalPages });
                    console.log(`Products Collected: ${cleanProducts.length}`);
                    success = true;
                    break;
                } catch (err) {
                    console.warn(`Retry ${attempt} failed`, err.message);
                    await sleep(5000);
                }
            }

            if (!success) {
                console.error(`Skipped page ${page + 1}`);
            }

            await sleep(randomDelay());
        }
    }

    console.log("----------------------------------------");
    if (typeof window.__PRODUCT_LIMIT__ !== "undefined" && window.__PRODUCT_LIMIT__ > 0) {
        cleanProducts.length = Math.min(cleanProducts.length, window.__PRODUCT_LIMIT__);
        console.log(`[TEST MODE] Truncated product list to ${cleanProducts.length} items for variant fetching`);
    }
    console.log(
        `Finished product listing (${cleanProducts.length} products)`
    );
    console.log("----------------------------------------");


    // --------------------------------------------------
    // Variant Statistics
    // --------------------------------------------------

    let completed = 0;

    let nextIndex = 0;

    let totalVariants = 0;

    let failedVariants = 0;


    // Buffer for streaming persistence to database
    window.__TATA_UNSAVED__ = window.__TATA_UNSAVED__ || [];
    window.drainUnsavedProducts = function () {
        const u = window.__TATA_UNSAVED__ || [];
        window.__TATA_UNSAVED__ = [];
        return u;
    };
    const alreadyCompletedSet = new Set(
        Array.isArray(window.__ALREADY_COMPLETED_IDS__) ? window.__ALREADY_COMPLETED_IDS__ : []
    );


    // --------------------------------------------------
    // Worker
    // --------------------------------------------------

    async function worker(workerId) {

        while (true) {

            const index = nextIndex++;

            if (index >= cleanProducts.length)
                break;

            const product = cleanProducts[index];

            if (!product.product_id) {
                completed++;
                updateProgress({ stage: "Collecting Variants", current: completed, total: cleanProducts.length });
                continue;
            }

            // Check if already persisted in database in earlier partial run
            if (alreadyCompletedSet.has(product.product_id)) {
                completed++;
                updateProgress({
                    stage: "Collecting Variants (Resuming)",
                    current: completed,
                    total: cleanProducts.length,
                    variant_count: totalVariants
                });
                continue;
            }

            try {

                product.variants =
                    await fetchVariants(
                        product.product_id
                    );

                totalVariants +=
                    product.variants.length;

            }

            catch (err) {

                failedVariants++;

                product.variants = [];

            }

            // Queue for streaming persistence
            window.__TATA_UNSAVED__.push(product);

            completed++;
            updateProgress({
                stage: "Collecting Variants",
                current: completed,
                total: cleanProducts.length,
                variant_count: totalVariants
            });

            if (totalVariants > 0 && Math.floor(totalVariants / 200) > Math.floor((totalVariants - product.variants.length) / 200)) {
                console.log(`[TATA CHECKPOINT] Checkpoint milestone: reached ${totalVariants} variants (${completed}/${cleanProducts.length} products).`);
            }

            if (completed % 25 === 0 || completed === cleanProducts.length) {
                console.log(
                    `[Worker ${workerId}] ` +
                    `${completed}/${cleanProducts.length}` +
                    ` | Product ${product.product_id}` +
                    ` | Variants: ${product.variants.length}` +
                    ` | Total Variants: ${totalVariants}` +
                    ` | Avg: ${(totalVariants / Math.max(completed, 1)).toFixed(2)}`
                );
            }

            // checkpoint every 100 products
            if (
                completed % 100 === 0 ||
                completed === cleanProducts.length
            ) {
                console.log("--------------------------------");
                console.log(
                    `Completed : ${completed}/${cleanProducts.length}`
                );
                console.log(
                    `Total Variants : ${totalVariants}`
                );
                console.log(
                    `Average Variants/Product : ${(
                        totalVariants /
                        Math.max(completed, 1)
                    ).toFixed(2)}`
                );
                console.log(
                    `Failed Variant Calls : ${failedVariants}`
                );
                console.log("--------------------------------");
            }

            await sleep(
                typeof window.__VARIANT_DELAY__ !== "undefined"
                    ? window.__VARIANT_DELAY__
                    : 30
            );

        }

    }


    console.log("----------------------------------------");
    console.log(
        `Fetching variants using ${CONCURRENCY} workers...`
    );
    updateProgress({ stage: "Collecting Variants", current: 0, total: cleanProducts.length });
    console.log("----------------------------------------");


    await Promise.all(

        Array.from(

            { length: CONCURRENCY },

            (_, i) => worker(i + 1)

        )

    );
    updateProgress({ stage: "Completed", current: cleanProducts.length, total: cleanProducts.length });
        // --------------------------------------------------
    // Download JSON
    // --------------------------------------------------

    function downloadJSON(products, filename) {

        const output = {

            schema_version: 1,

            source: "tatacliq",

            scrape_date:
                new Date().toISOString().slice(0, 10),

            scraped_at:
                new Date().toISOString(),

            total_products:
                products.length,

            total_variants:
                totalVariants,

            average_variants_per_product:
                Number(
                    (
                        totalVariants /
                        Math.max(products.length, 1)
                    ).toFixed(2)
                ),

            products

        };

        const blob = new Blob(
            [
                JSON.stringify(
                    output,
                    null,
                    2
                )
            ],
            {
                type: "application/json"
            }
        );

        const url =
            URL.createObjectURL(blob);

        const a =
            document.createElement("a");

        a.href = url;

        a.download = filename;

        document.body.appendChild(a);

        a.click();

        document.body.removeChild(a);

        URL.revokeObjectURL(url);

    }


    // --------------------------------------------------
    // Final Summary
    // --------------------------------------------------

    console.log("");
    console.log("========================================");
    console.log("SCRAPE COMPLETE");
    console.log("========================================");

    console.log(
        `Products           : ${cleanProducts.length}`
    );

    console.log(
        `Total Variants     : ${totalVariants}`
    );

    console.log(
        `Average Variants   : ${(
            totalVariants /
            Math.max(cleanProducts.length, 1)
        ).toFixed(2)}`
    );

    console.log(
        `Failed Variant API : ${failedVariants}`
    );

    console.log("========================================");


    // --------------------------------------------------
    // Final Output & Playwright Signal
    // --------------------------------------------------

    const output = {
        schema_version: 1,
        source: "tatacliq",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        total_products: cleanProducts.length,
        total_variants: totalVariants,
        average_variants_per_product: Number(
            (
                totalVariants /
                Math.max(cleanProducts.length, 1)
            ).toFixed(2)
        ),
        products: cleanProducts
    };

    window.output = cleanProducts;
    window.scraperResult = output;
    if (typeof window.updateProgress === "function") {
        window.updateProgress({ stage: "Completed", current: cleanProducts.length, total: cleanProducts.length });
    }
    window.__SCRAPER_DONE__ = true;

    // --------------------------------------------------
    // Download (Standalone Browser Only)
    // --------------------------------------------------

    if (typeof window.__IS_PLAYWRIGHT__ === "undefined") {
        downloadJSON(
            cleanProducts,
            "tatacliq_columbia_products.json"
        );

        console.log(
            "Downloaded tatacliq_columbia_products.json"
        );

        // Optional: Close tab after 2 seconds
        setTimeout(() => {
            try {
                window.close();
            } catch (_) {}
        }, 2000);
    } else {
        console.log(
            "[SCRAPER] Playwright execution: results stored in window.scraperResult and window.__SCRAPER_DONE__ = true"
        );
    }

})();

