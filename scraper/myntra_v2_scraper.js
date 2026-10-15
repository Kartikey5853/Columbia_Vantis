/**
 * New Myntra Columbia Scraper v2 (With Offers & Stock / Quantity)
 * 
 * Features:
 * - Collects Columbia product catalog from Myntra Gateway Search API
 * - Fetches PDP page HTML and extracts complete window.__myx.pdpData
 * - Extracts available offers:
 *     - Bank / EMI offers (HDFC, SBI, Axis, etc. with min spend, max discount, cashback %)
 *     - Coupons (BFF coupon codes, applicable offers, discount value)
 *     - Best price and direct offer links / T&C
 * - Extracts stock & quantity:
 *     - Variant level: size, skuId, available, availableCount, sellableInventoryCount
 *     - Product level: total catalog stock, overall availability
 * - Emits progress to window.__SCRAPER_PROGRESS__ and window.updateScraperProgress
 * - Generates clean JSON schema including offers, variants, and stock
 */

(async () => {
    const ROWS = 50;
    const PINCODE = "500038";

    let page = 1;
    let paginationContext = null;

    const products = [];
    const pdpCache = new Map();

    const sleep = ms =>
        new Promise(resolve => setTimeout(resolve, ms));

    const log = (...args) =>
        console.log(
            `[Myntra v2 ${new Date().toLocaleTimeString()}]`,
            ...args
        );

    const text = value =>
        value == null ? "" : String(value).trim();

    const number = value => {
        if (typeof value === "number" && Number.isFinite(value)) {
            return value;
        }
        const match = text(value)
            .replace(/,/g, "")
            .match(/-?\d+(?:\.\d+)?/);
        return match ? Number(match[0]) : null;
    };

    const first = (object, fields) => {
        if (!object || typeof object !== "object") return "";
        for (const f of fields) {
            if (object[f] !== undefined && object[f] !== null && object[f] !== "") {
                return object[f];
            }
        }
        return "";
    };

    const safeText = value => {
        const result = text(value).replace(/\s+/g, " ").trim();
        if (!result || result.length > 1000) return "";
        if (/<script|<html|<head|<body|window\.|document\.|javascript:|function\s*\(/i.test(result)) {
            return "";
        }
        return result;
    };

    const safeCode = value => {
        const code = text(value).toUpperCase();
        return /^[A-Z0-9][A-Z0-9_-]{1,79}$/.test(code) ? code : "";
    };

    const cleanHtmlEntities = str => {
        return text(str)
            .replace(/&lt;br\/?&gt;/gi, " ")
            .replace(/<br\s*\/?>/gi, " ")
            .replace(/&lt;/g, "<")
            .replace(/&gt;/g, ">")
            .replace(/&amp;/g, "&")
            .replace(/&quot;/g, '"')
            .replace(/&#39;/g, "'")
            .replace(/\s+/g, " ")
            .trim();
    };

    const updateProgress = (stage, current, total, extra = {}) => {
        const payload = {
            stage,
            current,
            total,
            ...extra,
            updated_at: new Date().toISOString()
        };
        window.__SCRAPER_PROGRESS__ = payload;
        log(stage, payload);
    };

    const normalizeOffer = (rawOffer, fallbackKind = "offer", currentPrice = 0) => {
        if (!rawOffer || typeof rawOffer !== "object") return null;

        const title = safeText(
            rawOffer.title ||
            rawOffer.heading ||
            rawOffer.offerTitle ||
            ""
        );

        const rawDesc =
            rawOffer.description ||
            rawOffer.message ||
            rawOffer.details ||
            rawOffer.offerText ||
            rawOffer.text ||
            "";

        const description = cleanHtmlEntities(rawDesc);
        const actionUrl = safeText(rawOffer.action || rawOffer.terms_url || rawOffer.termsUrl || "");

        // Text parsing for discount, min spend, max discount, coupon code
        const combinedText = `${title} ${description}`;

        const percentMatch = combinedText.match(/(\d+(?:\.\d+)?)\s*%/);
        const discountPercent = percentMatch ? Number(percentMatch[1]) : number(rawOffer.discount_percent);

        // Min Spend / Minimum Purchase
        const minSpendMatch = combinedText.match(
            /(?:min(?:imum)?\s*(?:spend|transaction|order|purchase)|mov\s*of|orders?\s*(?:above|over))\s*[:\-]?\s*₹?\s*([\d,]+)/i
        );
        const minSpend = minSpendMatch
            ? number(minSpendMatch[1])
            : number(rawOffer.minimum_transaction_amount || rawOffer.minSpend);

        // Max Discount
        const maxDiscMatch = combinedText.match(
            /(?:max(?:imum)?\s*discount|up\s*to|upto)\s*[:\-]?\s*₹?\s*([\d,]+)/i
        );
        const maxDiscount = maxDiscMatch
            ? number(maxDiscMatch[1])
            : number(rawOffer.maximum_discount || rawOffer.maxDiscount);

        // Coupon code
        const codeMatch = combinedText.match(/(?:coupon\s*code|use\s*code|code)\s*[:\-]?\s*([A-Z0-9]{3,20})/i);
        const code = safeCode(rawOffer.code || (codeMatch ? codeMatch[1] : ""));

        // Fixed coupon discount amount
        const discAmountMatch = combinedText.match(
            /(?:discount\s*[:\-]?\s*|off\s*[:\-]?\s*|upto\s*|save\s*)₹?\s*([\d,]+)\s*(?:off|discount)?/i
        );
        const discountAmount = discAmountMatch ? number(discAmountMatch[1]) : number(rawOffer.discount_amount);

        // Offer Price calculation
        let offerPrice = number(rawOffer.offer_price);
        if (offerPrice === null && currentPrice > 0) {
            if (discountPercent && discountPercent > 0) {
                const calculated = currentPrice * (1 - (discountPercent / 100));
                offerPrice = Math.max(0, Math.round(calculated));
            } else if (discountAmount && discountAmount > 0) {
                offerPrice = Math.max(0, Math.round(currentPrice - discountAmount));
            }
        }

        // Issuer / Bank
        const issuerMatch = combinedText.match(
            /\b(HDFC|SBI|ICICI|Axis|Kotak|IndusInd|Yes Bank|IDFC|RBL|HSBC|Bank of Baroda|Flipkart Axis)\b/i
        );
        const issuer = issuerMatch ? issuerMatch[0] : safeText(rawOffer.issuer);

        // Card Type
        const cardMatch = combinedText.match(/\b(Credit Card EMI|Credit Card|Debit Card|EMI|UPI)\b/i);
        const cardType = cardMatch ? cardMatch[0] : safeText(rawOffer.card_type);

        const kind =
            rawOffer.type === "BANK"
                ? "bank_offer"
                : (code ? "coupon" : fallbackKind);

        return {
            kind,
            code,
            title,
            description,
            offer_price: offerPrice,
            issuer,
            card_type: cardType,
            discount_percent: discountPercent,
            discount_amount: discountAmount,
            minimum_transaction_amount: minSpend,
            maximum_discount: maxDiscount,
            terms_url: actionUrl
        };
    };

    const extractPdpDataFromHtml = (html, currentPrice = 0) => {
        const result = {
            offers: [],
            sizes: [],
            sellerStock: null,
            maxQuantity: null
        };

        if (!html) return result;

        let pdpData = null;
        const myxIndex = html.indexOf("window.__myx = ");
        if (myxIndex !== -1) {
            const start = myxIndex + "window.__myx = ".length;
            try {
                // Find matching closing brace or parse first valid JSON object
                let depth = 0;
                let inStr = false;
                let esc = false;
                for (let i = start; i < html.length; i++) {
                    const c = html[i];
                    if (inStr) {
                        if (esc) esc = false;
                        else if (c === "\\") esc = true;
                        else if (c === '"') inStr = false;
                        continue;
                    }
                    if (c === '"') inStr = true;
                    else if (c === "{") depth++;
                    else if (c === "}") {
                        depth--;
                        if (depth === 0) {
                            const parsed = JSON.parse(html.slice(start, i + 1));
                            pdpData = parsed?.pdpData || parsed;
                            break;
                        }
                    }
                }
            } catch (_) {}
        }

        // Parse Offers from pdpData
        if (Array.isArray(pdpData?.offers)) {
            for (const off of pdpData.offers) {
                const normalized = normalizeOffer(off, "bank_offer", currentPrice);
                if (normalized) result.offers.push(normalized);
            }
        }

        // Parse New User / BFF Coupons from HTML
        const newUsersIdx = html.indexOf("newUsersPDP");
        if (newUsersIdx !== -1) {
            const objStart = html.indexOf("{", newUsersIdx);
            if (objStart !== -1) {
                try {
                    let depth = 0;
                    let inStr = false;
                    let esc = false;
                    for (let i = objStart; i < html.length; i++) {
                        const c = html[i];
                        if (inStr) {
                            if (esc) esc = false;
                            else if (c === "\\") esc = true;
                            else if (c === '"') inStr = false;
                            continue;
                        }
                        if (c === '"') inStr = true;
                        else if (c === "{") depth++;
                        else if (c === "}") {
                            depth--;
                            if (depth === 0) {
                                const nu = JSON.parse(html.slice(objStart, i + 1));
                                const normalized = normalizeOffer(
                                    {
                                        title: nu.title,
                                        description: nu.description,
                                        type: "coupon"
                                    },
                                    "coupon",
                                    currentPrice
                                );
                                if (normalized) result.offers.push(normalized);
                                break;
                            }
                        }
                    }
                } catch (_) {}
            }
        }

        // Parse Variant Sizes & Real Inventory Counts from pdpData
        if (Array.isArray(pdpData?.sizes)) {
            for (const s of pdpData.sizes) {
                const sellerData = Array.isArray(s.sizeSellerData) ? s.sizeSellerData[0] : null;
                const availableCount = number(sellerData?.availableCount ?? sellerData?.sellableInventoryCount);
                const isAvailable = s.available === true || (availableCount !== null && availableCount > 0);

                result.sizes.push({
                    size: text(s.label || s.size || s.sizeValue || ""),
                    sku_id: text(s.skuId || ""),
                    available: isAvailable,
                    quantity: availableCount !== null ? availableCount : (isAvailable ? true : false),
                    stock: availableCount !== null ? availableCount : (isAvailable ? true : false)
                });
            }
        }

        return result;
    };

    const fetchPdpDetails = async (url, currentPrice = 0) => {
        if (!url) {
            return { offers: [], sizes: [] };
        }

        try {
            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
                }
            });

            if (!response.ok) {
                return { offers: [], sizes: [] };
            }

            const html = await response.text();
            return extractPdpDataFromHtml(html, currentPrice);
        } catch (error) {
            log("PDP fetch error:", error.message, url);
            return { offers: [], sizes: [] };
        }
    };

    const fetchSearchPage = async (currentPage, currentContext) => {
        const offset = currentPage === 1 ? 0 : ((currentPage - 1) * ROWS) - 1;
        const url = `/gateway/v4/search/columbia?rawQuery=columbia&rows=${ROWS}&o=${offset}&plaEnabled=true&xdEnabled=false&isFacet=true&p=${currentPage}&pincode=${PINCODE}`;
        const headers = { accept: "application/json" };
        if (currentContext) headers["pagination-context"] = currentContext;

        log(`Fetching search page ${currentPage}`, `offset=${offset}`);
        const response = await fetch(url, {
            method: "GET",
            credentials: "same-origin",
            headers
        });

        if (!response.ok) {
            throw new Error(`Search HTTP ${response.status}`);
        }

        const data = await response.json();
        return {
            data,
            paginationContext: response.headers.get("pagination-context")
        };
    };

    log("Starting Myntra Columbia Scraper v2 (Offers & Stock)...");

    const rawCatalogProducts = [];

    while (true) {
        let result;
        try {
            result = await fetchSearchPage(page, paginationContext);
        } catch (error) {
            log(`Search stopped on page ${page}:`, error.message);
            break;
        }

        paginationContext = result.paginationContext || paginationContext;
        const data = result.data;
        const pageProducts =
            data?.products ||
            data?.results?.products ||
            data?.searchData?.results?.products ||
            [];

        const totalPages = Math.max(1, Math.ceil(Number(data.totalCount || 0) / ROWS));

        for (const item of pageProducts) {
            const pId = String(item.productId || item.id || "");
            if (!pId) continue;

            const pUrl = item.landingPageUrl
                ? `https://www.myntra.com/${item.landingPageUrl.replace(/^\/+/, "")}`
                : "";

            const price = Number(item.discountedPrice ?? item.price ?? item.mrp ?? 0) || 0;
            const mrp = Number(item.mrp ?? item.price ?? item.discountedPrice ?? 0) || 0;

            rawCatalogProducts.push({
                product_id: pId,
                title: item.productName || item.name || "",
                color: item.primaryColour || item.color || "",
                price,
                mrp,
                url: pUrl,
                image_url: item.searchImage || item.image || "",
                search_inventory: item.inventoryInfo || []
            });
        }

        updateProgress("Collecting Search Catalog", page, totalPages, {
            catalog_products: rawCatalogProducts.length
        });

        if (data.hasNextPage === false || pageProducts.length === 0 || page >= totalPages || page >= 100) {
            break;
        }

        page++;
        await sleep(1200);
    }

    log(`Search complete. Total products collected: ${rawCatalogProducts.length}`);

    // Deduplicate unique PDP URLs to minimize network calls
    const uniqueUrls = [...new Set(rawCatalogProducts.map(p => p.url).filter(Boolean))];
    log(`Fetching PDP offers & exact stock for ${uniqueUrls.length} unique styles...`);

    const CONCURRENCY = 3;
    let nextUrlIndex = 0;
    let completedPdp = 0;

    async function pdpWorker(workerId) {
        while (true) {
            const idx = nextUrlIndex++;
            if (idx >= uniqueUrls.length) break;

            const url = uniqueUrls[idx];
            const matchingProduct = rawCatalogProducts.find(p => p.url === url);
            const price = matchingProduct ? matchingProduct.price : 0;

            const pdpData = await fetchPdpDetails(url, price);
            pdpCache.set(url, pdpData);

            completedPdp++;
            updateProgress("Extracting Offers & Stock", completedPdp, uniqueUrls.length, {
                offers_cached: pdpData.offers.length
            });

            if (completedPdp % 10 === 0 || completedPdp === uniqueUrls.length) {
                log(
                    `[Worker ${workerId}] ${completedPdp}/${uniqueUrls.length}` +
                    ` | Offers: ${pdpData.offers.length} | Sizes: ${pdpData.sizes.length}`
                );
            }

            await sleep(400 + Math.random() * 400);
        }
    }

    await Promise.all(
        Array.from({ length: CONCURRENCY }, (_, i) => pdpWorker(i + 1))
    );

    // Assemble final normalized product catalog
    for (const raw of rawCatalogProducts) {
        const pdp = pdpCache.get(raw.url) || { offers: [], sizes: [] };
        const offers = pdp.offers || [];
        const sizes = pdp.sizes && pdp.sizes.length > 0 ? pdp.sizes : [];

        let totalSellableStock = 0;
        let anyAvailable = false;

        const variants = sizes.map(s => {
            if (typeof s.stock === "number") totalSellableStock += s.stock;
            if (s.available) anyAvailable = true;
            return {
                size: s.size,
                sku: s.sku_id,
                available: s.available,
                quantity: s.quantity,
                stock: s.stock
            };
        });

        products.push({
            source: "myntra",
            product_id: raw.product_id,
            title: raw.title,
            color: raw.color,
            price: raw.price,
            mrp: raw.mrp,
            available: anyAvailable || raw.price > 0,
            stock: totalSellableStock > 0 ? totalSellableStock : (anyAvailable ? true : false),
            total_sellable_stock: totalSellableStock,
            url: raw.url,
            image_url: raw.image_url,
            variants,
            offers,
            scraped_at: new Date().toISOString()
        });
    }

    const output = {
        schema_version: 2,
        source: "myntra",
        scrape_date: new Date().toISOString().slice(0, 10),
        scraped_at: new Date().toISOString(),
        total_products: products.length,
        total_offers: products.reduce((acc, p) => acc + p.offers.length, 0),
        products
    };

    window.__MYNTRA_PRODUCTS__ = products;
    window.__MYNTRA_FINAL_RESULT__ = output;
    window.__MYNTRA_SCRAPER_DONE__ = true;

    updateProgress("Completed", products.length, products.length, {
        total_products: products.length,
        total_offers: output.total_offers
    });

    log("Myntra Scraper v2 Complete!", {
        products: products.length,
        total_offers: output.total_offers
    });

    return output;
})();
