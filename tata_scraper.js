(async () => {

    // --------------------------------------------------
    // Helpers
    // --------------------------------------------------

    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

    const randomDelay = () =>
        1500 + Math.floor(Math.random() * 2000);


    // --------------------------------------------------
    // Config
    // --------------------------------------------------

    const PAGE_SIZE = 40;

    const CONCURRENCY = 5;
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

    async function fetchVariants(productId) {

        try {

            const res = await fetch(
                DETAIL_URL(productId),
                {
                    headers: {
                        Accept: "application/json"
                    }
                }
            );

            if (!res.ok)
                throw new Error(`HTTP ${res.status}`);

            const data = await res.json();

            const rawVariants =
                data.variantOptions || [];

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

        }

        catch (err) {

            console.warn(
                "Variant fetch failed:",
                productId,
                err.message
            );

            return [];

        }

    }


    // --------------------------------------------------
    // Product Storage
    // --------------------------------------------------

    const cleanProducts = [];


    function processProducts(products) {

        const scrapedAt =
            new Date().toISOString();

        const priceValue = value =>

            Number(

                value?.value ??

                value?.rawValue ??

                String(
                    value?.formattedValue || ""
                ).replace(/[^0-9.]/g, "")

            ) || 0;


        for (const p of products) {

            cleanProducts.push({

                source: "tatacliq",

                product_id:
                    String(p.productId || ""),

                sku: "",

                ean: "",

                available:
                    !!p.inStockFlag,

                title:
                    p.productname || "",

                price:
                    priceValue(
                        p.price?.sellingPrice
                    ),

                mrp:
                    priceValue(
                        p.price?.mrpPrice
                    ) ||
                    priceValue(
                        p.price?.sellingPrice
                    ),

                image_url:
                    p.imageURL
                        ? (
                            p.imageURL.startsWith("http")
                                ? p.imageURL
                                : "https:" + p.imageURL
                        )
                        : "",

                url:
                    p.webURL
                        ? "https://www.tatacliq.com" +
                          p.webURL
                        : "",

                variants: [],

                scraped_at: scrapedAt

            });

        }

    }
        // --------------------------------------------------
    // Fetch Listing Pages
    // --------------------------------------------------

    console.log("Fetching first page...");

    const first = await fetchPage(0);

    const totalPages = first.pagination.totalPages;
    const totalResults = first.pagination.totalResults;

    console.log(
        `Found ${totalPages} pages | ${totalResults} products`
    );

    processProducts(first.searchresult);
    updateProgress({ stage: "Collecting Products", current: 1, total: totalPages });

    console.log(
        `Collected ${cleanProducts.length} products`
    );


    for (let page = 1; page < totalPages; page++) {

        let success = false;

        for (let attempt = 1; attempt <= 3; attempt++) {

            try {

                console.log(
                    `Listing Page ${page + 1}/${totalPages} (Attempt ${attempt})`
                );

                const data = await fetchPage(page);

                processProducts(data.searchresult);
                updateProgress({ stage: "Collecting Products", current: page + 1, total: totalPages });

                console.log(
                    `Products Collected: ${cleanProducts.length}`
                );

                success = true;

                break;

            }

            catch (err) {

                console.warn(
                    `Retry ${attempt} failed`,
                    err.message
                );

                await sleep(5000);

            }

        }

        if (!success) {

            console.error(
                `Skipped page ${page + 1}`
            );

        }

        await sleep(randomDelay());

    }


    console.log("----------------------------------------");
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

            completed++;
            updateProgress({ stage: "Collecting Variants", current: completed, total: cleanProducts.length });

            console.log(

                `[Worker ${workerId}] ` +

                `${completed}/${cleanProducts.length}` +

                ` | Product ${product.product_id}` +

                ` | Variants: ${product.variants.length}` +

                ` | Total Variants: ${totalVariants}` +

                ` | Avg: ${(
                    totalVariants /
                    completed
                ).toFixed(2)}`

            );

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
                        completed
                    ).toFixed(2)}`
                );

                console.log(
                    `Failed Variant Calls : ${failedVariants}`
                );

                console.log("--------------------------------");

            }

            await sleep(
                1000 + Math.random() * 1000
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
    // Download
    // --------------------------------------------------

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

})();
