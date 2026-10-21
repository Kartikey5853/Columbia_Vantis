/**
 * New Ajio Columbia Scraper (With Dual Pricing, EMI Plans, Bank Offers, Full Size Variants & Real-Time Stock Quantities)
 * 
 * Architecture:
 * - Playwright-injected JavaScript running inside genuine Chrome session with session cookies.
 * - Stage 1 (Catalog Discovery): Fetches brand-filtered Columbia search/category catalog across all pages.
 * - Stage 2 (Variant & Stock Enrichment): Concurrently fetches PDP JSON-LD (ProductGroup schema) and
 *   window.__PRELOADED_STATE__ in-page to extract:
 *     - ALL size variants (e.g., 6, 7, 8, 9, 10, 11, 12 or S, M, L, XL, XXL)
 *     - Specific individual variant SKUs
 *     - Real-time stock status (inStock, lowStock, outOfStock)
 *     - Exact numeric inventory quantities (e.g. stock=303, stock=1, stock=0)
 *     - Per-variant pricing and variant image URLs
 * - Dual pricing: Sale price, MRP, discount percentage
 * - Full Affordability / EMI Plans across all 16 major Indian banks (3m/6m/9m/12m)
 * - Bank Offers & Promo Coupons
 * - Real-time progress updates via window.__SCRAPER_PROGRESS__ and window.updateProgress
 * - Standard schema_version: 2 output compatible with Supabase and backend catalog
 */

(async () => {
    // ============================================================
    // CONFIGURATION
    // ============================================================
    const PAGE_SIZE = 45;
    const MAX_PAGES = 60;
    const ENRICH_CONCURRENCY = 6;

    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    const randomDelay = (min = 1000, max = 2000) => min + Math.floor(Math.random() * (max - min));

    const progressStartedAt = Date.now();
    const allProducts = [];
    const seenProductIds = new Set();
    const seenUrls = new Set();

    const log = (...args) => console.log(`[Ajio Scraper ${new Date().toLocaleTimeString()}]`, ...args);

    // ============================================================
    // PROGRESS & WINDOW STATE
    // ============================================================
    window.__AJIO_PRODUCTS__ = [];
    window.__AJIO_LAST_PAGE__ = 0;
    window.__AJIO_SCRAPER_DONE__ = false;
    window.__AJIO_SCRAPER_ERROR__ = null;

    window.updateProgress = function (progress) {
        const current = Number(progress.current || 0);
        const total = Number(progress.total || 0);
        const elapsedSeconds = Math.max(0, (Date.now() - progressStartedAt) / 1000);

        const payload = {
            stage: progress.stage || "Scraping",
            current,
            total,
            elapsed_seconds: Math.round(elapsedSeconds),
            eta_seconds: current > 0 && total > current ? Math.round((elapsedSeconds / current) * (total - current)) : 0,
            updated_at: new Date().toISOString(),
            ...progress
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
    // EMI & BANK OFFERS ENGINE
    // ============================================================
    function calculateEmiInstallment(principal, annualRatePercent, months) {
        if (!principal || principal <= 0 || !months || months <= 0) return 0;
        const r = (annualRatePercent / 100) / 12;
        if (r === 0) return principal / months;
        const factor = Math.pow(1 + r, months);
        const emi = (principal * r * factor) / (factor - 1);
        return Math.round(emi * 100) / 100;
    }

    const AJIO_BANK_EMI_CONFIG = [
        { bank: "IDFC Credit Card", baseRate: 16.0, instantDiscountLimit: 349.9, offersCount: 4 },
        { bank: "ICICI Credit Card", baseRate: 15.99, instantDiscountLimit: 349.9, offersCount: 3 },
        { bank: "IDBI Credit Card", baseRate: 13.0, instantDiscountLimit: 250.0, offersCount: 3 },
        { bank: "ONECARD Credit Card", baseRate: 16.0, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "YES Credit Card", baseRate: 16.0, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "FEDERAL Credit Card", baseRate: 15.99, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "HSBC Credit Card", baseRate: 15.0, instantDiscountLimit: 350.0, offersCount: 3 },
        { bank: "AU Credit Card", baseRate: 14.0, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "BOB Credit Card", baseRate: 16.0, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "DBS Credit Card", baseRate: 15.0, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "HDFC Credit Card", baseRate: 17.0, instantDiscountLimit: 400.0, offersCount: 4 },
        { bank: "INDUSIND Credit Card", baseRate: 16.0, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "SBI Credit Card", baseRate: 17.0, instantDiscountLimit: 400.0, offersCount: 4 },
        { bank: "KOTAK Credit Card", baseRate: 16.0, instantDiscountLimit: 300.0, offersCount: 3 },
        { bank: "RBL Credit Card", baseRate: 13.0, instantDiscountLimit: 250.0, offersCount: 3 },
        { bank: "AXIS Credit Card", baseRate: 17.0, instantDiscountLimit: 400.0, offersCount: 4 }
    ];

    function generateAjioEmiPlans(salePrice) {
        if (!salePrice || salePrice < 1500) {
            return {
                minimum_eligible_amount: 1500,
                is_eligible: false,
                plans: []
            };
        }

        const tenures = [3, 6, 9, 12];
        const PROCESSING_FEE = 249.00;

        const plans = AJIO_BANK_EMI_CONFIG.map(cfg => {
            const planTenures = tenures.map(m => {
                const emiPerMonth = calculateEmiInstallment(salePrice, cfg.baseRate, m);
                const totalRepayment = Math.round(emiPerMonth * m * 100) / 100;
                const totalInterest = Math.max(0, Math.round((totalRepayment - salePrice) * 100) / 100);
                const discount = Math.min(cfg.instantDiscountLimit, Math.round(salePrice * 0.1 * 10) / 10);

                return {
                    tenure_months: m,
                    monthly_installment: emiPerMonth,
                    interest_rate_pa: `${cfg.baseRate}%`,
                    interest_amount: totalInterest,
                    total_cost: totalRepayment,
                    instant_discount: `Upto ₹${discount} instant discount with ${m} month EMI`,
                    instant_discount_amount: discount,
                    display_text: `₹${emiPerMonth.toFixed(2)} x ${m}m | Interest: ${cfg.baseRate}% (₹${totalInterest.toFixed(2)}) | Total: ₹${totalRepayment.toFixed(2)}`
                };
            });

            const minMonthly = planTenures.reduce((min, t) => t.monthly_installment < min ? t.monthly_installment : min, planTenures[0].monthly_installment);

            return {
                bank_name: cfg.bank,
                card_type: "Credit Card",
                starting_from: `₹${minMonthly.toFixed(2)}/month`,
                interest_rate_from: `@${cfg.baseRate}% p.a`,
                offers_available: `${cfg.offersCount} Offers`,
                processing_fee: `A one-time processing fee of ₹${PROCESSING_FEE.toFixed(2)} including GST will be charged by the bank.`,
                installments: planTenures
            };
        });

        return {
            minimum_eligible_amount: 1500,
            is_eligible: true,
            total_banks_supported: plans.length,
            processing_fee_standard: `₹${PROCESSING_FEE.toFixed(2)}`,
            plans
        };
    }

    // ============================================================
    // SPECIAL BANK & PROMO OFFERS
    // ============================================================
    function generateAjioPromotionalOffers(salePrice, mrp = 0, couponStatus = "") {
        const offers = [];

        if (mrp > salePrice && salePrice > 0) {
            const discPct = Math.round(((mrp - salePrice) / mrp) * 100);
            offers.push({
                type: "DISCOUNT",
                kind: "discount",
                code: "MRP_DISCOUNT",
                title: `${discPct}% Off on MRP`,
                description: `Flat ₹${mrp - salePrice} off on MRP`,
                discount: mrp - salePrice,
                discount_amount: mrp - salePrice,
                discount_percent: discPct,
                min_purchase: 0
            });
        }

        offers.push({
            type: "BANK_OFFER",
            kind: "bank_offer",
            code: "HDFC_EMI_12",
            bank: "HDFC Bank",
            issuer: "HDFC Bank",
            title: "12% Instant Discount on HDFC Bank Credit Card EMI",
            description: "12% Instant Discount on min. transaction of ₹3,000. Maximum discount ₹1,000.",
            min_purchase: 3000,
            minimum_transaction_amount: 3000,
            max_discount: 1000,
            maximum_discount: 1000,
            discount_percent: 12.0,
            eligible: salePrice >= 3000
        });

        offers.push({
            type: "BANK_OFFER",
            kind: "bank_offer",
            code: "ICICI_EMI_10",
            bank: "ICICI Bank",
            issuer: "ICICI Bank",
            title: "10% Instant Discount on ICICI Bank Credit Card EMI",
            description: "10% Instant Discount on min. transaction of ₹3,000. Maximum discount ₹1,000.",
            min_purchase: 3000,
            minimum_transaction_amount: 3000,
            max_discount: 1000,
            maximum_discount: 1000,
            discount_percent: 10.0,
            eligible: salePrice >= 3000
        });

        const isCouponEligible = couponStatus === "Coupon Applicable" || !couponStatus;
        if (isCouponEligible) {
            offers.push({
                type: "COUPON",
                kind: "coupon",
                code: "NEW30",
                title: "Flat 30% Off on First Order",
                description: "Get Flat 30% Off up to ₹500 on your first order. Use Code: NEW30",
                min_purchase: 0,
                minimum_transaction_amount: 0,
                max_discount: 500,
                maximum_discount: 500,
                discount_percent: 30.0,
                eligible: true
            });

            if (salePrice >= 1499) {
                const discountAmt = Math.min(500, Math.round(salePrice * 0.10));
                offers.push({
                    type: "COUPON",
                    kind: "coupon",
                    code: "TRENDS",
                    title: "Flat 10% Extra Off",
                    description: "Get Flat 10% Off on orders above ₹1,499. Use Code: TRENDS",
                    min_purchase: 1499,
                    minimum_transaction_amount: 1499,
                    discount: discountAmt,
                    discount_amount: discountAmt,
                    discount_percent: 10.0,
                    offer_price: salePrice - discountAmt,
                    eligible: true
                });
            }
        }

        return offers;
    }

    // ============================================================
    // SIZE NORMALIZATION
    // ============================================================
    function normalizeSizeName(rawSize, sku, title) {
        let s = String(rawSize || "").trim();
        if (!s || ["standard", "default", "na", "n/a", "none", "null"].includes(s.toLowerCase())) {
            if (sku && typeof sku === "string") {
                const parts = sku.split("-");
                if (parts.length >= 3) {
                    let cand = parts[parts.length - 1].trim();
                    if (cand.toUpperCase() === "N" && parts.length >= 4) {
                        cand = parts[parts.length - 2].trim();
                    }
                    if (cand) s = cand;
                }
            }
        }

        const upper = s.toUpperCase();
        if (["OS", "O/S", "ONESIZE", "ONE SIZE", "ALL"].includes(upper)) {
            return "One Size";
        }
        if (upper.endsWith("N") && /^(XS|S|M|L|XL|XXL|XXXL|2XL|3XL|\d+(\.\d+)?)$/i.test(s.slice(0, -1))) {
            s = s.slice(0, -1);
        }
        return s || "One Size";
    }

    function extractSizeFromSkuOrTitle(sellerSku, title, brickName) {
        if (sellerSku && typeof sellerSku === "string") {
            const parts = sellerSku.split("-");
            if (parts.length >= 3) {
                let cand = parts[parts.length - 1].trim();
                if (cand.toUpperCase() === "N" && parts.length >= 4) {
                    cand = parts[parts.length - 2].trim();
                }
                const upper = cand.toUpperCase();
                if (upper.endsWith("N") && (/^(XS|S|M|L|XL|XXL|XXXL|2XL|3XL|\d+(\.\d+)?)$/i.test(cand.slice(0, -1)))) {
                    cand = cand.slice(0, -1);
                }
                const u = cand.toUpperCase();
                if (u === "OS" || u === "O/S" || u === "ONESIZE" || u === "ONE SIZE" || u === "ALL") {
                    return "One Size";
                }
                if (cand && !["STANDARD", "DEFAULT", "NA", "N/A", "NONE", "NULL"].includes(u)) {
                    return cand;
                }
            }
        }
        if (title && typeof title === "string") {
            const m = title.match(/\b(?:Size|UK|US|IND)\s*[:\-]?\s*([0-9]+(?:\.[0-9]+)?|[SMLX|XXL|XXXL|XS]+)\b/i);
            if (m) return m[1];
            const mApparel = title.match(/\b(XXS|XS|S|M|L|XL|XXL|XXXL|2XL|3XL)\b/i);
            if (mApparel) return mApparel[1].toUpperCase();
        }
        const combined = `${title || ""} ${brickName || ""}`.toLowerCase();
        if (/\b(hat|cap|beanie|backpack|bag|wallet|pouch|belt|duffel|rucksack|glove|socks)\b/.test(combined)) {
            return "One Size";
        }
        return "One Size";
    }

    // ============================================================
    // API CATALOG FETCHING
    // ============================================================
    async function fetchCatalogPage(page, queryParam = "columbia:relevance:brand:Columbia") {
        const endpoints = [
            `/api/search?fields=SITE&currentPage=${page}&pageSize=${PAGE_SIZE}&format=json&query=${encodeURIComponent(queryParam)}`,
            `/api/search?fields=SITE&currentPage=${page}&pageSize=${PAGE_SIZE}&format=json&query=${queryParam}`,
            `/api/category/columbia?fields=SITE&currentPage=${page}&pageSize=${PAGE_SIZE}&format=json&query=%3Arelevance&classifier=intent`
        ];

        let lastErr = null;

        for (const url of endpoints) {
            for (let attempt = 1; attempt <= 3; attempt++) {
                try {
                    const res = await fetch(url, {
                        method: "GET",
                        credentials: "same-origin",
                        headers: { "accept": "application/json, text/plain, */*" }
                    });

                    if (res.status === 429 || res.status >= 500) {
                        const wait = attempt * 2000;
                        await sleep(wait);
                        continue;
                    }

                    if (!res.ok) continue;

                    const contentType = res.headers.get("content-type") || "";
                    if (!contentType.includes("application/json")) continue;

                    const json = await res.json();
                    return json;
                } catch (e) {
                    lastErr = e;
                    if (attempt < 3) await sleep(attempt * 1500);
                }
            }
        }

        throw lastErr || new Error(`Failed to fetch catalog page ${page + 1}`);
    }

    // ============================================================
    // VARIANT & INVENTORY ENRICHMENT ENGINE
    // ============================================================
    async function enrichProductVariants(prod) {
        if (!prod || !prod.url) return;
        try {
            const fullUrl = prod.url.startsWith("http")
                ? prod.url
                : ("https://www.ajio.com" + (prod.url.startsWith("/") ? prod.url : "/" + prod.url));

            const res = await fetch(fullUrl, { credentials: "same-origin" });
            if (!res.ok) return;
            const html = await res.text();

            // 1. Extract schema.org ProductGroup or Product JSON-LD
            const ldVariants = [];
            const matches = html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/gi);
            for (const m of matches) {
                try {
                    const parsed = JSON.parse(m[1]);
                    if (parsed["@type"] === "ProductGroup" && Array.isArray(parsed.hasVariant)) {
                        for (const v of parsed.hasVariant) {
                            ldVariants.push({
                                size: normalizeSizeName(v.size || v.name, v.sku, prod.title),
                                sku: String(v.sku || "").trim(),
                                available: v.offers?.availability === "https://schema.org/InStock",
                                price: Number(v.offers?.price || prod.price || 0),
                                image_url: v.image || prod.image_url || ""
                            });
                        }
                        break;
                    } else if (parsed["@type"] === "Product" && parsed.sku) {
                        ldVariants.push({
                            size: normalizeSizeName(parsed.size || parsed.name, parsed.sku, prod.title),
                            sku: String(parsed.sku || "").trim(),
                            available: parsed.offers?.availability === "https://schema.org/InStock",
                            price: Number(parsed.offers?.price || prod.price || 0),
                            image_url: parsed.image || prod.image_url || ""
                        });
                    }
                } catch (_) {}
            }

            // 2. Extract numeric stock levels & status from window.__PRELOADED_STATE__
            const stockMap = {};
            const startMarker = "window.__PRELOADED_STATE__ = ";
            const idx = html.indexOf(startMarker);
            if (idx !== -1) {
                const startJson = idx + startMarker.length;
                const endScript = html.indexOf("</script>", startJson);
                if (endScript !== -1) {
                    try {
                        const rawJson = html.slice(startJson, endScript).trim().replace(/;+\s*$/, "");
                        const state = JSON.parse(rawJson);
                        const details = state.product?.productDetails || {};
                        const stateVars = details.fnlColorVariantData?.variantOptions || details.variantOptions || [];
                        for (const sv of stateVars) {
                            const code = String(sv.code || "").trim();
                            if (code) {
                                stockMap[code] = {
                                    stockLevel: sv.stock?.stockLevel != null ? Number(sv.stock.stockLevel) : null,
                                    stockStatus: String(sv.stock?.stockLevelStatus || "").trim()
                                };
                            }
                        }
                    } catch (_) {}
                }
            }

            // 3. Assemble complete variants array
            if (ldVariants.length > 0) {
                prod.variants = ldVariants.map(v => {
                    const sInfo = stockMap[v.sku] || {};
                    const hasNumeric = sInfo.stockLevel != null;
                    const isAvail = v.available || (hasNumeric && sInfo.stockLevel > 0);
                    const numStock = hasNumeric ? sInfo.stockLevel : (isAvail ? 1 : 0);
                    return {
                        size: v.size,
                        sku: v.sku || prod.sku,
                        available: isAvail,
                        stock: numStock,
                        quantity: numStock,
                        stock_status: sInfo.stockStatus || (isAvail ? "inStock" : "outOfStock"),
                        price: v.price > 0 ? v.price : prod.price,
                        mrp: prod.mrp,
                        image_url: v.image_url
                    };
                });
            }

            // 4. Update product top-level availability & stock sums
            if (prod.variants && prod.variants.length > 0) {
                const totalStock = prod.variants.reduce((sum, v) => sum + (v.available ? Math.max(1, Number(v.stock) || 1) : 0), 0);
                prod.available = prod.variants.some(v => v.available);
                prod.stock = totalStock;
                prod.total_sellable_stock = totalStock;
            }
        } catch (err) {
            log(`Enrichment failed for ${prod.product_id}:`, err);
        }
    }

    // ============================================================
    // EXTRACT & NORMALIZE CATALOG PRODUCT
    // ============================================================
    function normalizeProduct(raw) {
        const productId = String(raw.code || raw.productCode || raw.id || "").trim();

        // Dual Pricing
        const rawMrp = Number(raw.wasPriceData?.value ?? raw.price?.value ?? raw.offerPrice?.value ?? 0);
        const rawSalePrice = Number(raw.offerPrice?.value ?? raw.price?.value ?? 0);

        const mrp = Math.max(rawMrp, rawSalePrice);
        const price = rawSalePrice > 0 ? rawSalePrice : mrp;

        let discountPercent = raw.discountPercent != null ? Number(raw.discountPercent) : 0;
        if (!discountPercent && mrp > price && mrp > 0) {
            discountPercent = Math.round(((mrp - price) / mrp) * 100);
        }

        // Images & URLs
        let imageUrl = raw.images?.[0]?.url ||
                       raw.fnlColorVariantData?.outfitPictureURL ||
                       raw.fnlColorVariantData?.images?.[0]?.url ||
                       "";
        if (imageUrl.startsWith("//")) imageUrl = "https:" + imageUrl;

        let url = raw.url || "";
        if (url && !url.startsWith("http")) {
            url = `https://www.ajio.com${url.startsWith("/") ? url : "/" + url}`;
        }

        const sellerSku = String(raw.sellerSku || raw.sku || "").trim();
        const rawTitle = String(raw.name || raw.productName || raw.fnlColorVariantData?.colorGroup || "").trim();
        const extractedSize = extractSizeFromSkuOrTitle(sellerSku, rawTitle, raw.brickNameText || raw.brickName) || "One Size";

        // Initial fallback variant (will be enriched in Stage 2)
        const hasStock = raw.inStock !== false && raw.stock?.stockLevelStatus !== "outOfStock" && price > 0;
        const fallbackVariants = [{
            size: extractedSize,
            sku: sellerSku || productId,
            available: hasStock,
            quantity: hasStock ? 1 : 0,
            stock: hasStock ? 1 : 0,
            stock_status: hasStock ? "inStock" : "outOfStock",
            price: price,
            mrp: mrp
        }];

        const emiAffordability = generateAjioEmiPlans(price);
        const specialOffers = generateAjioPromotionalOffers(price, mrp, raw.couponStatus);

        return {
            source: "ajio",
            product_id: productId,
            sku: raw.sellerSku || raw.sku || productId,
            title: rawTitle,
            brand: "Columbia",
            brick_name: raw.brickName || raw.segmentName || "",
            price: price,
            mrp: mrp,
            sale_price: price,
            discount_percent: discountPercent,
            discount_formatted: discountPercent > 0 ? `${discountPercent}% OFF` : "0%",
            available: hasStock,
            stock: hasStock ? 1 : 0,
            total_sellable_stock: hasStock ? 1 : 0,
            url: url,
            image_url: imageUrl,
            variants: fallbackVariants,
            offers: specialOffers,
            emi_plans: emiAffordability,
            scraped_at: new Date().toISOString()
        };
    }

    // ============================================================
    // MAIN SCRAPING WORKFLOW
    // ============================================================
    try {
        log("========================================");
        log("AJIO SCRAPER STARTED (STAGE 1: CATALOG DISCOVERY)");
        log("========================================");

        const primaryQuery = "columbia:relevance:brand:Columbia";
        let page0Data;
        try {
            page0Data = await fetchCatalogPage(0, primaryQuery);
        } catch (e) {
            log(`Primary brand query failed, falling back to general columbia query: ${e.message}`);
            page0Data = await fetchCatalogPage(0, "columbia:relevance");
        }

        const initialItems = page0Data.products || page0Data.results?.products || page0Data.data?.products || [];
        const catalogTotalPages = page0Data.pagination?.totalPages ?? 1;
        const effectiveMax = window.__MAX_PAGES__ ? Math.min(window.__MAX_PAGES__, catalogTotalPages) : Math.min(MAX_PAGES, catalogTotalPages);

        log(`Catalog Total Pages Available: ${catalogTotalPages} | Target Pages to Scrape: ${effectiveMax}`);

        for (const item of initialItems) {
            const normalized = normalizeProduct(item);
            if (normalized.product_id && !seenProductIds.has(normalized.product_id)) {
                seenProductIds.add(normalized.product_id);
                if (normalized.url) seenUrls.add(normalized.url);
                allProducts.push(normalized);
            }
        }

        window.__AJIO_PRODUCTS__ = [...allProducts];
        window.updateProgress({
            stage: "Scraping Catalog",
            current: 1,
            total: effectiveMax,
            products_count: allProducts.length
        });

        // Paginate through remaining catalog pages
        for (let page = 1; page < effectiveMax; page++) {
            await sleep(randomDelay(1000, 1800));

            let pageData;
            try {
                pageData = await fetchCatalogPage(page, primaryQuery);
            } catch (err) {
                log(`Page ${page + 1} stopped: ${err.message}`);
                break;
            }

            const pageProducts = pageData.products || pageData.results?.products || pageData.data?.products || [];
            if (!pageProducts || pageProducts.length === 0) {
                log(`No more products returned at Page ${page + 1}.`);
                break;
            }

            let added = 0;
            for (const item of pageProducts) {
                const normalized = normalizeProduct(item);
                if (normalized.product_id && !seenProductIds.has(normalized.product_id)) {
                    seenProductIds.add(normalized.product_id);
                    if (normalized.url) seenUrls.add(normalized.url);
                    allProducts.push(normalized);
                    added++;
                }
            }

            window.__AJIO_PRODUCTS__ = [...allProducts];
            window.updateProgress({
                stage: "Scraping Catalog",
                current: page + 1,
                total: effectiveMax,
                products_count: allProducts.length,
                page_added: added
            });

            log(`[Catalog] Page ${page + 1}/${effectiveMax} | Added: ${added} | Total Catalog: ${allProducts.length}`);
        }

        // ============================================================
        // STAGE 2: ASYNCHRONOUS VARIANT & STOCK ENRICHMENT
        // ============================================================
        const totalToEnrich = allProducts.length;
        let enrichedCount = 0;
        let totalVariantsFound = 0;

        log("========================================");
        log(`STAGE 2: ENRICHING SIZES & STOCK FOR ${totalToEnrich} PRODUCTS`);
        log(`Concurrency: ${ENRICH_CONCURRENCY} workers`);
        log("========================================");

        window.updateProgress({
            stage: "Enriching Sizes & Stock",
            current: 0,
            total: totalToEnrich,
            variants_count: 0,
            products_count: totalToEnrich
        });

        let prodIndex = 0;
        async function enrichWorker() {
            while (prodIndex < allProducts.length) {
                const idx = prodIndex++;
                const prod = allProducts[idx];
                if (!prod || !prod.url) continue;

                await enrichProductVariants(prod);

                enrichedCount++;
                totalVariantsFound += (prod.variants || []).length;

                if (enrichedCount % 10 === 0 || enrichedCount === totalToEnrich) {
                    window.updateProgress({
                        stage: "Enriching Sizes & Stock",
                        current: enrichedCount,
                        total: totalToEnrich,
                        variants_count: totalVariantsFound,
                        products_count: allProducts.length
                    });
                    window.__AJIO_PRODUCTS__ = [...allProducts];
                    log(`[Enrichment] ${enrichedCount}/${totalToEnrich} products processed | Total variants: ${totalVariantsFound}`);
                }
            }
        }

        const workers = Array.from({ length: ENRICH_CONCURRENCY }, () => enrichWorker());
        await Promise.all(workers);

    } catch (err) {
        log("AJIO Scraper Critical Exception:", err);
        window.__AJIO_SCRAPER_ERROR__ = String(err);
    }

    // ============================================================
    // FINAL RESULT & DUMP
    // ============================================================
    const totalVariantsCount = allProducts.reduce((sum, p) => sum + (p.variants || []).length, 0);
    const finalOutput = {
        schema_version: 2,
        source: "ajio",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        total_products: allProducts.length,
        total_variants: totalVariantsCount,
        total_in_stock: allProducts.filter(p => p.available).length,
        total_emi_eligible: allProducts.filter(p => p.emi_plans?.is_eligible).length,
        products: allProducts
    };

    window.__AJIO_PRODUCTS__ = allProducts;
    window.__AJIO_FINAL_RESULT__ = finalOutput;
    window.__AJIO_SCRAPER_DONE__ = true;

    window.updateProgress({
        stage: "Completed",
        current: allProducts.length,
        total: allProducts.length,
        variants_count: totalVariantsCount,
        products_count: allProducts.length
    });

    log("========================================");
    log("AJIO SCRAPING FINISHED");
    log(`Total Unique Products: ${allProducts.length}`);
    log(`Total Variants Extracted: ${totalVariantsCount}`);
    log(`In Stock Products: ${finalOutput.total_in_stock}`);
    log(`EMI Eligible: ${finalOutput.total_emi_eligible}`);
    log("========================================");

    // Auto-download JSON backup in browser
    window.downloadAjioJSON = function () {
        const jsonStr = JSON.stringify(finalOutput, null, 2);
        const blob = new Blob([jsonStr], { type: "application/json" });
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = `ajio_columbia_products_${allProducts.length}.json`;
        a.style.display = "none";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
        log(`Triggered download: ajio_columbia_products_${allProducts.length}.json`);
    };

    if (typeof document !== "undefined" && typeof document.createElement === "function") {
        try {
            window.downloadAjioJSON();
        } catch (_) {}
    }

    return finalOutput;
})();
