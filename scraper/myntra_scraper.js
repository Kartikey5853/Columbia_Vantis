(async () => {

    // ============================================================
    // CONFIG
    // ============================================================

    const sleep = ms =>
        new Promise(resolve => setTimeout(resolve, ms));

    const randomDelay = () =>
        500 + Math.floor(Math.random() * 600);

    const ROWS = 50;

    let page = typeof window.__START_PAGE__ !== "undefined" && Number(window.__START_PAGE__) > 0
        ? Number(window.__START_PAGE__)
        : 1;
    const productLimit = window.__PRODUCT_LIMIT__ ? Number(window.__PRODUCT_LIMIT__) : 0;

    let paginationContext = null;

    const allProducts = [];
    window.__MYNTRA_UNSAVED__ = window.__MYNTRA_UNSAVED__ || [];
    window.drainUnsavedProducts = function () {
        const u = window.__MYNTRA_UNSAVED__ || [];
        window.__MYNTRA_UNSAVED__ = [];
        return u;
    };
    const progressStartedAt = Date.now();
    window.updateProgress = function (progress) {
        const current = Number(progress.current || 0);
        const total = Number(progress.total || 0);
        const elapsedSeconds = Math.max(0, (Date.now() - progressStartedAt) / 1000);
        const remainingSeconds = current > 0 && total > current
            ? Math.round((elapsedSeconds / current) * (total - current))
            : 0;
        const payload = {
            ...progress,
            current,
            total,
            elapsed_seconds: Math.round(elapsedSeconds),
            eta_seconds: remainingSeconds,
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


    // ============================================================
    // FETCH ONE PAGE
    // ============================================================

    async function fetchPage(page, paginationContext) {

        const offset =
            page === 1
                ? 0
                : ((page - 1) * ROWS) - 1;


        const url =
            `/gateway/v4/search/columbia` +
            `?rawQuery=columbia` +
            `&rows=${ROWS}` +
            `&o=${offset}` +
            `&plaEnabled=true` +
            `&xdEnabled=false` +
            `&isFacet=true` +
            `&p=${page}` +
            `&pincode=500038`;


        console.log(
            `Fetching Page ${page} | Offset ${offset}`
        );


        // Build headers
        const headers = {
            "accept": "application/json",
            "x-meta-app": "channel=web",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin"
        };


        // Send previous page's pagination context
        if (paginationContext) {

            headers["pagination-context"] =
                paginationContext;

            console.log(
                `Sending pagination-context for Page ${page}`
            );

        }


        let response;
        let lastError;
        for (let attempt = 1; attempt <= 5; attempt++) {
            try {
                response = await fetch(
                    url,
                    {
                        method: "GET",
                        credentials: "same-origin",
                        headers
                    }
                );

                if (response.status === 429 || response.status >= 500) {
                    console.warn(
                        `HTTP ${response.status} on Page ${page}, waiting ${attempt * 3000}ms before retry ${attempt}/5...`
                    );
                    if (attempt < 5) {
                        await sleep(attempt * 3000);
                        continue;
                    }
                }

                if (response.status === 400) {
                    console.log(`HTTP 400 on Page ${page} (end of catalog reached). Halting.`);
                    return null;
                }

                if (!response.ok) {
                    throw new Error(
                        `HTTP ${response.status} on Page ${page}`
                    );
                }

                break;
            } catch (err) {
                lastError = err;
                console.warn(`Network or HTTP error on Myntra page ${page}, attempt ${attempt}/5:`, err);
                if (attempt < 5) {
                    await sleep(attempt * 3000);
                    continue;
                }
                throw err;
            }
        }

        if (!response || !response.ok) {
            throw lastError || new Error(`Failed to fetch Myntra page ${page} after 5 attempts`);
        }


        // Read pagination context BEFORE parsing
        const nextPaginationContext =
            response.headers.get(
                "pagination-context"
            );

        const rawText = await response.text();
        let data;
        try {
            data = JSON.parse(rawText);
        } catch (jsonErr) {
            console.warn(`Response was not valid JSON (received ${rawText.slice(0, 60)}...). Checking window.__myx...`);
            if (typeof window.__myx !== "undefined" && window.__myx?.searchData) {
                data = window.__myx.searchData;
                console.log(`Successfully recovered data from window.__myx!`);
            } else {
                throw new Error(`Failed to parse response as JSON. Body preview: ${rawText.slice(0, 150)}`);
            }
        }

        return {
            data,
            paginationContext:
                nextPaginationContext
        };

    }


    // ============================================================
    // MAIN SCRAPER
    // ============================================================

    while (true) {

        if (window.__STOP_REQUESTED__) {
            console.log("Stop requested. Halting pagination cleanly.");
            break;
        }

        let result;


        try {

            result =
                await fetchPage(
                    page,
                    paginationContext
                );

        } catch (error) {

            console.error(
                `FAILED ON PAGE ${page}`,
                error
            );


            console.log(
                "Scraping stopped."
            );


            console.log(
                `Raw products saved: ${allProducts.length}`
            );


            console.log(
                "Your collected data is still available at:"
            );


            console.log(
                "window.__MYNTRA_PRODUCTS__"
            );


            break;

        }

        if (!result) {
            console.log("No further data returned. Halting pagination.");
            break;
        }


        const data =
            result.data;


        // Update pagination context
        if (result.paginationContext) {

            paginationContext =
                result.paginationContext;


            console.log(
                `✓ Received pagination-context`
            );

        } else {

            console.warn(
                `⚠ No pagination-context returned on Page ${page}`
            );

        }


        // ========================================================
        // FIND PRODUCTS
        // ========================================================

        const products =

            data?.products ||

            data?.results?.products ||

            data?.searchData?.results?.products ||

            [];
        const totalPages = Math.max(1, Math.ceil(Number(data.totalCount || 0) / ROWS));
        updateProgress({ stage: "Collecting Products", current: page, total: totalPages });


        console.log(
            `Page ${page} returned ${products.length} products`
        );


        // ========================================================
        // NORMALIZE PRODUCTS
        // ========================================================

        const scrapedAt =
            new Date().toISOString();

        const pageItems = [];

        for (const product of products) {

            const productId =
                String(
                    product.productId ||
                    product.id ||
                    ""
                );

            if (!productId) {
                continue;
            }

            const sizeEntries = Array.isArray(product.inventoryInfo) && product.inventoryInfo.length
                ? product.inventoryInfo
                : String(product.sizes || "").split(",").map(label => ({ label: label.trim(), skuId: "" })).filter(x => x.label);
            for (const sizeEntry of (sizeEntries.length ? sizeEntries : [{ label: "", skuId: "" }])) {
                const item = {
                    product_id: productId,
                    source: "myntra",
                    sku: "",
                    ean: "",
                    size: sizeEntry.label || product.size || product.sizeName || product.variantSize || "",
                    color: product.primaryColour || product.color || product.colorName || product.variantColor || "",
                    variant_id: String(sizeEntry.skuId || product.buyButtonWinnerSkuId || product.variantId || product.variant_id || product.sku || ""),
                    title: product.productName || product.name || "",
                    price: (Number(product.discountedPrice ?? product.price ?? product.mrp ?? 0)) || 0,
                    mrp: (Number(product.mrp ?? product.price ?? product.discountedPrice ?? 0)) || 0,
                    url: product.landingPageUrl
                        ? `https://www.myntra.com/${product.landingPageUrl.replace(/^\/+/, "")}`
                        : "",
                    image_url: product.searchImage || product.image || "",
                    available: true,
                    scraped_at: scrapedAt
                };
                pageItems.push(item);
                allProducts.push(item);

                if (productLimit > 0 && allProducts.length >= productLimit) {
                    break;
                }
            }
            if (productLimit > 0 && allProducts.length >= productLimit) {
                break;
            }
        }

        // Push page checkpoint to unsaved buffer for database persistence
        window.__MYNTRA_UNSAVED__.push({
            page: page,
            products: pageItems
        });
        window.__MYNTRA_LAST_PAGE__ = page;
        try {
            if (typeof window.localStorage !== "undefined") {
                window.localStorage.setItem("myntra_last_page", String(page));
            }
        } catch (_) {}

        if (productLimit > 0 && allProducts.length >= productLimit) {
            console.log(`Product limit ${productLimit} reached. Stopping Myntra pagination.`);
            break;
        }


        // ========================================================
        // CREATE LIVE DEDUPLICATED BACKUP
        // ========================================================

        const uniqueMap =
            new Map();


        for (const product of allProducts) {

            if (
                !uniqueMap.has(
                    `${product.product_id}|${product.size || ""}|${product.color || ""}|${product.variant_id || ""}`
                )
            ) {

                uniqueMap.set(
                    `${product.product_id}|${product.size || ""}|${product.color || ""}|${product.variant_id || ""}`,
                    product
                );

            }

        }


        const uniqueProducts =
            [...uniqueMap.values()];


        // SAVE BACKUP TO WINDOW
        // This survives even if a later fetch fails.

        window.__MYNTRA_PRODUCTS__ =
            uniqueProducts;


        window.__MYNTRA_RAW_PRODUCTS__ =
            allProducts;


        window.__MYNTRA_LAST_PAGE__ =
            page;


        window.__MYNTRA_PAGINATION_CONTEXT__ =
            paginationContext;


        // ========================================================
        // PROGRESS
        // ========================================================

        console.log(
            "--------------------------------"
        );


        console.log(
            `Page: ${page}`
        );


        console.log(
            `Raw collected: ${allProducts.length}`
        );


        console.log(
            `Unique products: ${uniqueProducts.length}`
        );


        console.log(
            `Duplicates: ${
                allProducts.length -
                uniqueProducts.length
            }`
        );


        console.log(
            `API totalCount: ${data.totalCount}`
        );


        console.log(
            `hasNextPage: ${data.hasNextPage}`
        );


        console.log(
            "--------------------------------"
        );


        // ========================================================
        // FINISHED?
        // ========================================================

        if (
            data.hasNextPage === false ||
            products.length === 0 ||
            page >= totalPages
        ) {

            console.log(
                "✓ Myntra reports no more pages."
            );

            break;

        }


        // ========================================================
        // SAFETY LIMIT
        // ========================================================

        if (page >= 100) {

            console.warn(
                "Safety limit of 100 pages reached."
            );

            break;

        }


        // ========================================================
        // NEXT PAGE
        // ========================================================

        page++;


        const delay =
            randomDelay();


        console.log(
            `Waiting ${delay}ms before Page ${page}...`
        );


        await sleep(
            delay
        );

    }


    // ============================================================
    // FINAL DEDUPLICATION
    // ============================================================

    const finalMap =
        new Map();


    for (
        const product
        of allProducts
    ) {

        if (
            product.product_id &&
            !finalMap.has(
                `${product.product_id}|${product.size || ""}|${product.color || ""}|${product.variant_id || ""}`
            )
        ) {

            finalMap.set(
                `${product.product_id}|${product.size || ""}|${product.color || ""}|${product.variant_id || ""}`,
                product
            );

        }

    }


    const finalProducts =
        [...finalMap.values()];


    // Final backup

    window.__MYNTRA_PRODUCTS__ =
        finalProducts;
    window.__MYNTRA_SCRAPER_DONE__ = true;
    window.__SCRAPER_DONE__ = true;
    window.scraperResult = {
        schema_version: 1,
        source: "myntra",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        products: finalProducts,
        total_products: finalProducts.length
    };
    updateProgress({ stage: "Completed", current: page, total: page });


    // ============================================================
    // FINAL STATS
    // ============================================================

    console.log(
        "========================================"
    );


    console.log(
        "MYNTRA SCRAPING FINISHED"
    );


    console.log(
        `Last Page: ${page}`
    );


    console.log(
        `Raw Listings: ${allProducts.length}`
    );


    console.log(
        `Unique Products: ${finalProducts.length}`
    );


    console.log(
        `Duplicates Removed: ${
            allProducts.length -
            finalProducts.length
        }`
    );


    console.log(
        "Backup:"
    );


    console.log(
        "window.__MYNTRA_PRODUCTS__"
    );


    console.log(
        "========================================"
    );


    // ============================================================
    // DOWNLOAD FUNCTION
    // ============================================================

    // Keep the helper for compatibility, but invoke it automatically so the
    // scraper produces a real download instead of a copy/paste blob.
    //
    // Run:
    //
    // downloadMyntraJSON()
    //
    // after scraping finishes.


    window.downloadMyntraJSON =
        function () {


            const products =
                window.__MYNTRA_PRODUCTS__ ||
                [];


            const json =
                JSON.stringify({ schema_version: 1, source: "myntra", scrape_date: new Date().toISOString().slice(0, 10), scraped_at: new Date().toISOString(), products },
                    null,
                    2
                );


            const blob =
                new Blob(
                    [json],
                    {
                        type:
                            "application/json"
                    }
                );


            const blobUrl =
                URL.createObjectURL(
                    blob
                );


            const a =
                document.createElement(
                    "a"
                );


            a.href =
                blobUrl;


            a.download =
                `myntra_columbia_products_${products.length}.json`;


            a.style.display =
                "none";


            document.body.appendChild(
                a
            );


            a.click();


            a.remove();


            setTimeout(
                () => {

                    URL.revokeObjectURL(
                        blobUrl
                    );

                },

                5000

            );


            console.log(
                `Download triggered: ${products.length} products`
            );
            if (typeof window.__IS_PLAYWRIGHT__ === "undefined") {
                setTimeout(() => { try { window.close(); } catch (_) {} }, 1500);
            }

        };


    // The Python runner reads window.__MYNTRA_PRODUCTS__ and writes the
    // finished JSON file directly. Do not create a blob navigation here:
    // Chrome/IDM can render that blob instead of saving it as a file.
    console.log("Myntra products are ready for the runner to save.");

})();
