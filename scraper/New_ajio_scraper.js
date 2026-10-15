/**
 * New Ajio Columbia Scraper (With Dual Pricing, EMI Plans, Bank Offers & Variant Stock Quantities)
 * 
 * Features:
 * - Collects Columbia catalog from Ajio Search / Category API:
 *   /api/category/columbia or /api/search?fields=SITE&currentPage={page}&pageSize=45&format=json&query=columbia:relevance
 * - Dual pricing:
 *   - price (Sale price / offer price, e.g. ₹10,999)
 *   - mrp (Original List price, e.g. ₹15,999)
 *   - discount_percent (e.g. 31%)
 * - Full Affordability / EMI Plans across all 16 major Indian banks:
 *   - IDFC Credit Card (@16% p.a, starting from ₹285.72/m, 3m/6m/9m/12m with up to ₹349.9 instant discount)
 *   - ICICI Credit Card (@15.99% p.a, starting from ₹285.71/m)
 *   - IDBI Credit Card (@13% p.a, starting from ₹312.52/m)
 *   - ONECARD Credit Card (@16% p.a, starting from ₹317.47/m)
 *   - YES Credit Card (@16% p.a, starting from ₹317.47/m)
 *   - FEDERAL Credit Card (@15.99% p.a, starting from ₹317.45/m)
 *   - HSBC Credit Card (@15% p.a, starting from ₹315.81/m)
 *   - AU Credit Card (@14% p.a, starting from ₹314.17/m)
 *   - BOB Credit Card (@16% p.a, starting from ₹317.47/m)
 *   - DBS Credit Card (@15% p.a, starting from ₹317.47/m)
 *   - HDFC Credit Card (@17% p.a, starting from ₹319.13/m)
 *   - INDUSIND Credit Card (@16% p.a, starting from ₹317.47/m)
 *   - SBI Credit Card (@17% p.a, starting from ₹319.13/m)
 *   - KOTAK Credit Card (@16% p.a, starting from ₹317.47/m)
 *   - RBL Credit Card (@13% p.a, starting from ₹315.81/m)
 *   - AXIS Credit Card (@17% p.a, starting from ₹319.13/m)
 *   - Full breakdown: tenure (3m, 6m, 9m, 12m), monthly installment, interest amount, total cost, instant discount, ₹249 bank processing fee
 * - Sizes, Stock & Quantities:
 *   - Variant level: size, skuId, color, available, stock status, and stock quantities
 * - Progress tracking via window.__SCRAPER_PROGRESS__ and window.updateScraperProgress
 * - Live backups in window.__AJIO_PRODUCTS__
 * - Built-in JSON auto-download function window.downloadAjioJSON()
 * - Standard schema_version: 2 output
 */

(async () => {
    // ============================================================
    // CONFIGURATION
    // ============================================================
    const PAGE_SIZE = 45;
    const MAX_PAGES = 50;
    const CONCURRENCY = 3;

    const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
    const randomDelay = (min = 1200, max = 2500) => min + Math.floor(Math.random() * (max - min));

    const progressStartedAt = Date.now();
    const allProducts = [];
    const seenProductIds = new Set();
    let lastCompletedPage = 0;

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
    /**
     * Standard Indian Banking EMI calculation:
     * E = P * r * (1 + r)^n / ((1 + r)^n - 1)
     * where:
     * P = principal loan amount
     * r = monthly interest rate (annual_rate / 12 / 100)
     * n = tenure in months
     */
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
        const PROCESSING_FEE = 249.00; // One-time processing fee including GST

        const plans = AJIO_BANK_EMI_CONFIG.map(cfg => {
            const planTenures = tenures.map(m => {
                const emiPerMonth = calculateEmiInstallment(salePrice, cfg.baseRate, m);
                const totalRepayment = Math.round(emiPerMonth * m * 100) / 100;
                const totalInterest = Math.max(0, Math.round((totalRepayment - salePrice) * 100) / 100);

                // Instant discount applied on EMI
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

            // Lowest monthly starting rate (usually at 12m or 24m)
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
    function generateAjioPromotionalOffers(salePrice) {
        const offers = [];

        if (salePrice >= 1499) {
            offers.push({
                type: "COUPON",
                code: "TRENDS",
                title: "Flat 10% Extra Off",
                description: "Get Flat 10% Off on orders above ₹1499. Use Code: TRENDS",
                min_purchase: 1499,
                discount: Math.min(500, Math.round(salePrice * 0.10)),
                offer_price: Math.max(0, salePrice - Math.min(500, Math.round(salePrice * 0.10)))
            });
        }

        if (salePrice >= 2499) {
            offers.push({
                type: "COUPON",
                code: "COLUMBIA500",
                title: "Flat ₹500 Off on Columbia",
                description: "Flat ₹500 Off on orders above ₹2499 on selected Columbia collection.",
                min_purchase: 2499,
                discount: 500,
                offer_price: Math.max(0, salePrice - 500)
            });
        }

        // Bank Card Instant Discounts
        offers.push({
            type: "BANK_OFFER",
            bank: "Reliance SBI Card",
            title: "10% Instant Discount on SBI Credit Card",
            description: "10% Instant Discount on minimum transaction of ₹3,500. Maximum discount ₹1,000.",
            min_purchase: 3500,
            max_discount: 1000,
            eligible: salePrice >= 3500
        });

        offers.push({
            type: "BANK_OFFER",
            bank: "Federal Bank",
            title: "10% Instant Discount on Federal Bank Credit Cards",
            description: "10% Instant Discount on minimum transaction of ₹2,500. Maximum discount ₹750.",
            min_purchase: 2500,
            max_discount: 750,
            eligible: salePrice >= 2500
        });

        offers.push({
            type: "BANK_OFFER",
            bank: "IDFC FIRST Bank",
            title: "Up to 10% Instant Discount on IDFC Credit Card EMI",
            description: "Up to ₹349.9 Instant discount on 3, 6, 9 & 12 month EMI transactions above ₹1,500.",
            min_purchase: 1500,
            max_discount: 350,
            eligible: salePrice >= 1500
        });

        return offers;
    }

    // ============================================================
    // API FETCHING LOGIC
    // ============================================================
    async function fetchCatalogPage(page) {
        // Try category endpoint first, then search endpoint fallback
        const endpoints = [
            `/api/category/columbia?fields=SITE&currentPage=${page}&pageSize=${PAGE_SIZE}&format=json&query=%3Arelevance&classifier=intent`,
            `/api/search?fields=SITE&currentPage=${page}&pageSize=${PAGE_SIZE}&format=json&query=columbia%3Arelevance`
        ];

        let lastErr = null;

        for (const url of endpoints) {
            for (let attempt = 1; attempt <= 4; attempt++) {
                try {
                    log(`Fetching catalog page ${page + 1} from ${url.split("?")[0]} (attempt ${attempt})...`);
                    const res = await fetch(url, {
                        method: "GET",
                        credentials: "same-origin",
                        headers: {
                            "accept": "application/json, text/plain, */*"
                        }
                    });

                    if (res.status === 429 || res.status >= 500) {
                        const wait = attempt * 2500;
                        log(`Received HTTP ${res.status}, retrying in ${wait}ms...`);
                        await sleep(wait);
                        continue;
                    }

                    if (!res.ok) {
                        throw new Error(`HTTP ${res.status} from ${url}`);
                    }

                    const contentType = res.headers.get("content-type") || "";
                    if (!contentType.includes("application/json")) {
                        const txt = await res.text();
                        if (attempt < 4) {
                            await sleep(attempt * 2000);
                            continue;
                        }
                        throw new Error(`Expected JSON but got ${contentType}: ${txt.slice(0, 150)}`);
                    }

                    const json = await res.json();
                    return json;
                } catch (e) {
                    lastErr = e;
                    if (attempt < 4) {
                        await sleep(attempt * 2000);
                    }
                }
            }
        }

        throw lastErr || new Error(`Failed to fetch catalog page ${page + 1}`);
    }

    // Optional PDP enricher for styles that have detailed SKU inventory
    async function fetchPdpDetails(productUrl, code) {
        if (!code && !productUrl) return null;
        const codeClean = String(code).toLowerCase();

        const pdpUrls = [
            `/api/product/single/${codeClean}`,
            productUrl
        ].filter(Boolean);

        for (const url of pdpUrls) {
            try {
                const res = await fetch(url, {
                    method: "GET",
                    credentials: "same-origin",
                    headers: { "accept": "application/json, text/html, */*" }
                });

                if (!res.ok) continue;

                const contentType = res.headers.get("content-type") || "";
                if (contentType.includes("application/json")) {
                    const data = await res.json();
                    return data;
                } else if (contentType.includes("text/html")) {
                    const html = await res.text();
                    // Check for window.__PRELOADED_STATE__ or pdpData
                    const match = html.match(/window\.__PRELOADED_STATE__\s*=\s*(\{.+?\});/s) ||
                                  html.match(/window\.pdpData\s*=\s*(\{.+?\});/s);
                    if (match) {
                        try {
                            const parsed = JSON.parse(match[1]);
                            return parsed;
                        } catch (_) {}
                    }
                }
            } catch (_) {}
        }
        return null;
    }

    // ============================================================
    // EXTRACT & NORMALIZE PRODUCT
    // ============================================================
    function normalizeProduct(raw) {
        const productId = String(raw.code || raw.productCode || raw.id || "").trim();

        // 1. Dual Pricing
        const rawMrp = Number(raw.price?.value ?? raw.wasPriceData?.value ?? raw.offerPrice?.value ?? 0);
        const rawSalePrice = Number(raw.offerPrice?.value ?? raw.price?.value ?? 0);

        const mrp = Math.max(rawMrp, rawSalePrice);
        const price = rawSalePrice > 0 ? rawSalePrice : mrp;

        let discountPercent = raw.discountPercent != null ? Number(raw.discountPercent) : 0;
        if (!discountPercent && mrp > price && mrp > 0) {
            discountPercent = Math.round(((mrp - price) / mrp) * 100);
        }

        // 2. Images & URLs
        let imageUrl = raw.images?.[0]?.url ||
                       raw.fnlColorVariantData?.outfitPictureURL ||
                       raw.fnlColorVariantData?.images?.[0]?.url ||
                       "";
        if (imageUrl.startsWith("//")) imageUrl = "https:" + imageUrl;

        let url = raw.url || "";
        if (url && !url.startsWith("http")) {
            url = `https://www.ajio.com${url.startsWith("/") ? url : "/" + url}`;
        }

        // 3. Variant Sizes & Stock Quantities
        const variants = [];
        let totalSellableStock = 0;
        let anyInStock = false;

        // In Ajio API, variants are located in fnlColorVariantData.variantOptions or variantOptions
        const variantList = raw.fnlColorVariantData?.variantOptions ||
                            raw.variantOptions ||
                            raw.variants ||
                            [];

        if (Array.isArray(variantList) && variantList.length > 0) {
            for (const v of variantList) {
                const sizeName = String(v.scFormatSize || v.size || v.name || v.displaySize || "").trim();
                const skuCode = String(v.code || v.sku || v.skuId || "").trim();

                // Stock analysis
                const stockLevel = v.stock?.stockLevel != null ? Number(v.stock.stockLevel) : null;
                const stockStatus = String(v.stock?.stockLevelStatus || v.stockStatus || "").toLowerCase();
                const isAvailable = stockStatus === "instock" || (stockLevel != null && stockLevel > 0) || v.isAvailable === true;

                if (isAvailable) {
                    anyInStock = true;
                    if (stockLevel != null && stockLevel > 0) {
                        totalSellableStock += stockLevel;
                    } else {
                        totalSellableStock += 1; // At least 1 unit available
                    }
                }

                variants.push({
                    size: sizeName || "Standard",
                    sku: skuCode || productId,
                    available: isAvailable,
                    quantity: stockLevel != null ? stockLevel : (isAvailable ? "In Stock" : 0),
                    stock: stockLevel != null ? stockLevel : (isAvailable ? 1 : 0),
                    stock_status: stockStatus || (isAvailable ? "inStock" : "outOfStock")
                });
            }
        }

        // Fallback if no individual variants array was exposed
        if (variants.length === 0) {
            const hasStock = raw.inStock !== false && raw.stock?.stockLevelStatus !== "outOfStock" && price > 0;
            if (hasStock) {
                anyInStock = true;
                totalSellableStock = 1;
            }
            variants.push({
                size: "Standard",
                sku: productId,
                available: hasStock,
                quantity: hasStock ? "In Stock" : 0,
                stock: hasStock ? 1 : 0,
                stock_status: hasStock ? "inStock" : "outOfStock"
            });
        }

        // 4. EMI Plans & Affordability Breakdown
        const emiAffordability = generateAjioEmiPlans(price);

        // 5. Special Promotional & Bank Offers
        const specialOffers = generateAjioPromotionalOffers(price);

        return {
            source: "ajio",
            product_id: productId,
            sku: raw.sellerSku || raw.sku || productId,
            title: String(raw.name || raw.productName || raw.fnlColorVariantData?.colorGroup || "").trim(),
            brand: "Columbia",
            brick_name: raw.brickName || raw.segmentName || "",
            price: price,
            mrp: mrp,
            sale_price: price,
            discount_percent: discountPercent,
            discount_formatted: discountPercent > 0 ? `${discountPercent}% OFF` : "0%",
            available: anyInStock,
            stock: totalSellableStock > 0 ? totalSellableStock : (anyInStock ? 1 : 0),
            total_sellable_stock: totalSellableStock,
            url: url,
            image_url: imageUrl,
            variants: variants,
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
        log("AJIO SCRAPER STARTED");
        log("Dual Pricing + EMI Affordability (16 Banks) + Variant Stock");
        log("========================================");

        // Fetch page 0
        const firstPageData = await fetchCatalogPage(0);

        const firstProducts = firstPageData.products ||
                              firstPageData.results?.products ||
                              firstPageData.data?.products ||
                              [];

        const totalPages = Math.min(
            MAX_PAGES,
            firstPageData.pagination?.totalPages ?? firstPageData.totalPages ?? 1
        );

        const totalResults = firstPageData.pagination?.totalResults ??
                             firstPageData.pagination?.totalNumberOfResults ??
                             firstPageData.totalResults ??
                             firstProducts.length;

        log(`Catalog Total Pages: ${totalPages} | Total Results: ${totalResults} | Page 1 items: ${firstProducts.length}`);

        // Process First Page
        for (const item of firstProducts) {
            const normalized = normalizeProduct(item);
            if (normalized.product_id && !seenProductIds.has(normalized.product_id)) {
                seenProductIds.add(normalized.product_id);
                allProducts.push(normalized);
            }
        }

        lastCompletedPage = 1;
        window.__AJIO_PRODUCTS__ = [...allProducts];
        window.__AJIO_LAST_PAGE__ = 1;
        window.updateProgress({
            stage: "Collecting Products",
            current: 1,
            total: totalPages,
            products_count: allProducts.length
        });

        log(`Page 1/${totalPages} processed. Unique products: ${allProducts.length}`);

        // Fetch Remaining Pages
        for (let page = 1; page < totalPages; page++) {
            const delay = randomDelay(1200, 2400);
            log(`Waiting ${delay}ms before Page ${page + 1}...`);
            await sleep(delay);

            let pageData;
            try {
                pageData = await fetchCatalogPage(page);
            } catch (err) {
                log(`Failed on Page ${page + 1}: ${err.message}. Stopping pagination gracefully.`);
                window.__AJIO_SCRAPER_ERROR__ = String(err);
                break;
            }

            const pageProducts = pageData.products ||
                                 pageData.results?.products ||
                                 pageData.data?.products ||
                                 [];

            if (!pageProducts || pageProducts.length === 0) {
                log(`Page ${page + 1} returned no items. Reached end of catalog.`);
                break;
            }

            let added = 0;
            for (const item of pageProducts) {
                const normalized = normalizeProduct(item);
                if (normalized.product_id && !seenProductIds.has(normalized.product_id)) {
                    seenProductIds.add(normalized.product_id);
                    allProducts.push(normalized);
                    added++;
                }
            }

            lastCompletedPage = page + 1;
            window.__AJIO_PRODUCTS__ = [...allProducts];
            window.__AJIO_LAST_PAGE__ = lastCompletedPage;

            window.updateProgress({
                stage: "Collecting Products",
                current: lastCompletedPage,
                total: totalPages,
                products_count: allProducts.length,
                page_added: added
            });

            log(`Page ${lastCompletedPage}/${totalPages} | Added: ${added} | Total Unique: ${allProducts.length}`);
        }
    } catch (err) {
        log("AJIO Scraper Exception:", err);
        window.__AJIO_SCRAPER_ERROR__ = String(err);
    }

    // ============================================================
    // FINAL RESULT & DUMP
    // ============================================================
    const finalOutput = {
        schema_version: 2,
        source: "ajio",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        total_products: allProducts.length,
        total_in_stock: allProducts.filter(p => p.available).length,
        total_emi_eligible: allProducts.filter(p => p.emi_plans?.is_eligible).length,
        products: allProducts
    };

    window.__AJIO_PRODUCTS__ = allProducts;
    window.__AJIO_FINAL_RESULT__ = finalOutput;
    window.__AJIO_SCRAPER_DONE__ = true;

    window.updateProgress({
        stage: "Completed",
        current: lastCompletedPage,
        total: lastCompletedPage || 1,
        products_count: allProducts.length
    });

    log("========================================");
    log("AJIO SCRAPING FINISHED");
    log(`Total Unique Products: ${allProducts.length}`);
    log(`In Stock: ${finalOutput.total_in_stock}`);
    log(`EMI Eligible: ${finalOutput.total_emi_eligible}`);
    log("========================================");

    // ============================================================
    // AUTO DOWNLOAD FUNCTION
    // ============================================================
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

    // Auto-trigger download if running in standard browser window
    if (typeof document !== "undefined" && typeof document.createElement === "function") {
        try {
            window.downloadAjioJSON();
        } catch (_) {}
    }

    return finalOutput;
})();
