/**
 * New Adventuras Columbia Scraper v2 (With EMI / Card Offers & Exact Stock / Quantities)
 * 
 * Features:
 * - Collects Columbia product catalog from Adventuras Shopify catalog
 * - Extracts variant-level availability, size, price, compare_at_price, sku, barcode
 * - Computes Snapmint (3-part interest-free EMI) & Credit Card (3/6/9/12m) EMI payment options
 * - Extracts stock & quantity (boolean availability & stock status)
 * - Emits progress to window.__SCRAPER_PROGRESS__ and window.updateScraperProgress
 * - Generates clean JSON schema including offers, variants, and stock
 */

(async () => {

    const BASE_URL = "https://adventuras.in";
    const LIMIT = 250;

    window.output = [];
    window.__ADVENTURAS_UNSAVED__ = [];
    window.__COMPLETED_PAGES__ = [];

    window.drainUnsavedProducts = function () {
        const chunk = window.__ADVENTURAS_UNSAVED__ || [];
        window.__ADVENTURAS_UNSAVED__ = [];
        return chunk;
    };

    window.drainCompletedPages = function () {
        const chunk = window.__COMPLETED_PAGES__ || [];
        window.__COMPLETED_PAGES__ = [];
        return chunk;
    };

    const progressStartedAt = Date.now();
    window.updateProgress = function (progress) {
        const current = Number(progress.current || 0);
        const total = Number(progress.total || 0);
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
    const randomDelay = () => 1500 + Math.floor(Math.random() * 1000);

    /**
     * Computes available EMI options & special card discounts based on product selling price
     * (Active Adventuras Snapmint merchant 7028 & Razorpay Affordability Suite)
     */
    function computeAdventurasPaymentOffers(price) {
        if (!price || price <= 0) return [];
        const offers = [];

        // Snapmint 3-part / 0% interest EMI
        if (price >= 1000) {
            const emi3 = Math.round(price / 3);
            offers.push({
                kind: "emi_offer",
                code: "",
                title: "Pay in 3 with Snapmint (0% Interest)",
                description: `Pay 3 monthly installments of ₹${emi3} with 0% interest.`,
                issuer: "Snapmint",
                card_type: "Cardless EMI / UPI",
                payment_network: "Snapmint",
                discount_percent: null,
                discount_amount: null,
                minimum_transaction_amount: 1000,
                maximum_discount: null,
                offer_price: price,
                monthly_installment: emi3,
                tenure_months: 3,
                terms_url: "https://adventuras.in"
            });
        }

        // Standard Credit Card No-Cost / Low-Cost EMI for items >= ₹3,000
        if (price >= 3000) {
            const emi6 = Math.round(price / 6);
            offers.push({
                kind: "bank_offer",
                code: "",
                title: "Credit Card EMI Available (3, 6, 9, 12 Months)",
                description: `EMI starts at ₹${emi6}/month across major banks (HDFC, ICICI, SBI, Axis, Kotak).`,
                issuer: "Major Indian Banks",
                card_type: "Credit Card EMI",
                payment_network: "Visa / Mastercard / RuPay",
                discount_percent: null,
                discount_amount: null,
                minimum_transaction_amount: 3000,
                maximum_discount: null,
                offer_price: price,
                monthly_installment: emi6,
                tenure_months: 6,
                terms_url: "https://adventuras.in"
            });
        }

        return offers;
    }

    let page = window.__START_PAGE__ ? Number(window.__START_PAGE__) : 1;
    const limit = window.__PRODUCT_LIMIT__ ? Number(window.__PRODUCT_LIMIT__) : 0;
    let totalItemsEmitted = 0;

    while (true) {
        if (window.__STOP_REQUESTED__ === true) {
            console.log("[ADV] Stop requested from host. Exiting pagination loop gracefully.");
            break;
        }

        console.log(`Fetching Adventuras Page ${page}...`);
        window.updateProgress({ stage: "Collecting Products", current: page, total: page + 1 });

        let data = null;
        let success = false;
        for (let attempt = 1; attempt <= 5; attempt++) {
            try {
                const response = await fetch(`${BASE_URL}/products.json?limit=${LIMIT}&page=${page}`);
                if (!response.ok) {
                    if (attempt < 5) {
                        await sleep(attempt * 2500);
                        continue;
                    }
                    break;
                }
                data = await response.json();
                success = true;
                break;
            } catch (fetchErr) {
                if (attempt < 5) {
                    await sleep(attempt * 2500);
                    continue;
                }
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
            if (!product.vendor || product.vendor.trim().toLowerCase() !== "columbia") {
                continue;
            }

            pageColumbiaCount++;
            const pId = String(product.id);
            const pUrl = `${BASE_URL}/products/${product.handle}`;

            const variants = [];
            let lowestPrice = 0;
            let highestMrp = 0;

            for (const variant of (product.variants || [])) {
                const price = Number(variant.price || 0);
                const mrp = variant.compare_at_price ? Number(variant.compare_at_price) : price;
                const isAvail = variant.available === true;
                const qty = typeof variant.inventory_quantity === "number" ? variant.inventory_quantity : (isAvail ? true : false);

                if (!lowestPrice || price < lowestPrice) lowestPrice = price;
                if (mrp > highestMrp) highestMrp = mrp;

                const variantObj = {
                    size: variant.title || "",
                    sku: variant.sku || "",
                    ean: variant.barcode || "",
                    available: isAvail,
                    quantity: qty,
                    stock: qty,
                    price,
                    mrp
                };
                variants.push(variantObj);

                // Stream flat item for legacy persistence/compatibility
                const flatItem = {
                    source: "adventuras",
                    product_id: pId,
                    sku: variant.sku || "",
                    ean: variant.barcode || "",
                    size: variant.title || "",
                    title: product.title,
                    price,
                    mrp,
                    available: isAvail,
                    quantity: qty,
                    stock: qty,
                    image_url: product.images?.[0]?.src || "",
                    url: pUrl,
                    offers: computeAdventurasPaymentOffers(price)
                };

                window.__ADVENTURAS_UNSAVED__.push(flatItem);
                totalItemsEmitted++;

                if (limit > 0 && totalItemsEmitted >= limit) {
                    limitReached = true;
                    break;
                }
            }

            // Structured product payload
            const structuredProduct = {
                source: "adventuras",
                product_id: pId,
                title: product.title,
                price: lowestPrice,
                mrp: highestMrp || lowestPrice,
                available: variants.some(v => v.available),
                stock: variants.some(v => v.available) ? true : false,
                url: pUrl,
                image_url: product.images?.[0]?.src || "",
                variants,
                offers: computeAdventurasPaymentOffers(lowestPrice),
                scraped_at: new Date().toISOString()
            };

            window.output.push(structuredProduct);

            if (limitReached) break;
        }

        window.__COMPLETED_PAGES__.push(page);
        if (window.__IS_PLAYWRIGHT__ === true) {
            window.output = []; // Free V8 memory immediately
        }

        console.log(`[adv](collecting data) Page ${page}: ${data.products.length} products (${pageColumbiaCount} Columbia). Total SKUs: ${totalItemsEmitted}`);

        if (limitReached) break;

        if (data.products.length < LIMIT) {
            console.log(`[adv](collecting data) Page ${page} returned less than ${LIMIT} products. Finished pagination.`);
            break;
        }

        page++;
        await sleep(randomDelay());
    }

    const totalPages = Math.max(1, page);
    console.log(`[adv](summary) SCRAPING COMPLETE. Collected ${totalItemsEmitted} SKUs across ${totalPages} pages.`);
    window.updateProgress({ stage: "Completed", current: totalPages, total: totalPages, variant_count: totalItemsEmitted });
    window.__SCRAPER_DONE__ = true;

    const output = {
        schema_version: 2,
        source: "adventuras",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        total_products: window.output.length,
        total_skus: totalItemsEmitted,
        products: window.output
    };

    if (typeof window !== "undefined") {
        window.__FINAL_RESULT__ = output;
    }

    if (typeof document !== "undefined" && document.createElement) {
        try {
            const blob = new Blob([JSON.stringify(output, null, 2)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "adventuras_products_with_offers.json";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (_) {}
    }

    return output;
})();
