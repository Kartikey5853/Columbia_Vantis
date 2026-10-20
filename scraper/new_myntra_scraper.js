(async () => {
    const ROWS = 50;
    const PINCODE = "500038";

    let page = 1;
    let paginationContext = null;

    const products = [];
    const offerCache = new Map();

    const sleep = ms =>
        new Promise(resolve => setTimeout(resolve, ms));

    const log = (...args) =>
        console.log(
            `[Myntra ${new Date().toLocaleTimeString()}]`,
            ...args
        );

    const text = value =>
        value == null ? "" : String(value).trim();

    const number = value => {
        if (
            typeof value === "number" &&
            Number.isFinite(value)
        ) {
            return value;
        }

        const match = text(value)
            .replace(/,/g, "")
            .match(/-?\d+(?:\.\d+)?/);

        return match ? Number(match[0]) : null;
    };

    const first = (object, fields) => {
        if (!object || typeof object !== "object") {
            return "";
        }

        for (const field of fields) {
            if (
                object[field] !== undefined &&
                object[field] !== null &&
                object[field] !== ""
            ) {
                return object[field];
            }
        }

        return "";
    };

    const safeText = value => {
        const result = text(value)
            .replace(/\s+/g, " ")
            .trim();

        if (!result || result.length > 500) {
            return "";
        }

        if (
            /<script|<html|<head|<body|window\.|document\.|javascript:|function\s*\(/i
                .test(result)
        ) {
            return "";
        }

        return result;
    };

    const safeCode = value => {
        const code = text(value).toUpperCase();

        return /^[A-Z0-9][A-Z0-9_-]{1,79}$/.test(code)
            ? code
            : "";
    };

    const updateProgress = (
        stage,
        current,
        total,
        extra = {}
    ) => {
        const payload = {
            stage,
            current,
            total,
            ...extra,
            updated_at: new Date().toISOString()
        };

        window.__SCRAPER_PROGRESS__ =
            payload;

        log(stage, payload);
    };

    const inventoryRecord = entry => {
        const source =
            entry &&
            typeof entry === "object"
                ? entry
                : { label: entry };

        const quantity = number(
            first(source, [
                "quantity",
                "stockCount",
                "inventory",
                "availableQuantity",
                "qty",
                "units"
            ])
        );

        const availableValue = first(
            source,
            [
                "available",
                "isAvailable",
                "inStock",
                "isInStock"
            ]
        );

        const available =
            availableValue === ""
                ? quantity === null
                    ? null
                    : quantity > 0
                : typeof availableValue === "string"
                    ? ![
                        "false",
                        "0",
                        "no",
                        "outofstock",
                        "soldout"
                    ].includes(
                        availableValue
                            .toLowerCase()
                            .replace(/\s+/g, "")
                    )
                    : Boolean(availableValue);

        return {
            label: text(
                first(source, [
                    "label",
                    "size",
                    "sizeName",
                    "value",
                    "displayName"
                ])
            ),

            skuId: text(
                first(source, [
                    "skuId",
                    "sku",
                    "variantId",
                    "id"
                ])
            ),

            available,
            quantity
        };
    };

    const offerKey = offer =>
        JSON.stringify([
            offer.kind,
            offer.code,
            offer.title,
            offer.description,
            offer.issuer,
            offer.card_type,
            offer.payment_network,
            offer.discount_percent,
            offer.discount_amount,
            offer.minimum_transaction_amount,
            offer.maximum_discount
        ]);

    const makeOffer = (
        value,
        fallbackKind = "offer"
    ) => {
        if (
            !value ||
            typeof value !== "object" ||
            Array.isArray(value)
        ) {
            return null;
        }

        const title = safeText(
            first(value, [
                "title",
                "heading",
                "offerTitle"
            ])
        );

        const description = safeText(
            first(value, [
                "description",
                "message",
                "details",
                "offerText",
                "label",
                "text"
            ])
        );

        const issuer = safeText(
            first(value, [
                "bank",
                "bankName",
                "issuer",
                "issuerName",
                "provider",
                "partner"
            ])
        );

        if (!title && !description && !issuer) {
            return null;
        }

        return {
            kind:
                safeText(
                    first(value, [
                        "type",
                        "offerType",
                        "kind"
                    ])
                ) || fallbackKind,

            code: safeCode(
                first(value, [
                    "code",
                    "couponCode",
                    "coupon"
                ])
            ),

            title,
            description,
            issuer,

            card_type: safeText(
                first(value, [
                    "cardType",
                    "paymentType",
                    "instrument",
                    "mode"
                ])
            ),

            payment_network: safeText(
                first(value, [
                    "network",
                    "cardNetwork",
                    "paymentNetwork"
                ])
            ),

            discount_percent: number(
                first(value, [
                    "discountPercent",
                    "discountPercentage",
                    "percent",
                    "percentage"
                ])
            ),

            discount_amount: number(
                first(value, [
                    "discountAmount",
                    "cashbackAmount",
                    "amount",
                    "value"
                ])
            ),

            minimum_transaction_amount: number(
                first(value, [
                    "minSpend",
                    "minimumSpend",
                    "minTransaction",
                    "minimumTransaction",
                    "minAmount"
                ])
            ),

            maximum_discount: number(
                first(value, [
                    "maxDiscount",
                    "maximumDiscount",
                    "discountCap",
                    "cap"
                ])
            ),

            validity: safeText(
                first(value, [
                    "validity",
                    "validTill",
                    "endDate",
                    "expiry",
                    "expiresAt"
                ])
            ),

            terms_url: safeText(
                first(value, [
                    "termsUrl",
                    "termsURL",
                    "termsLink"
                ])
            )
        };
    };

    const normalizeOffers = object => {
        const result = [];
        const seen = new Set();

        const add = (value, kind) => {
            if (Array.isArray(value)) {
                value.forEach(item =>
                    add(item, kind)
                );
                return;
            }

            const offer =
                makeOffer(value, kind);

            if (!offer) {
                return;
            }

            const key =
                offerKey(offer);

            if (!seen.has(key)) {
                seen.add(key);
                result.push(offer);
            }
        };

        for (const field of [
            "offers",
            "offerData",
            "bestOffers",
            "bankOffers",
            "couponOffers",
            "coupons",
            "discountOffers",
            "paymentOffers"
        ]) {
            if (
                object &&
                object[field] !== undefined
            ) {
                add(
                    object[field],
                    /coupon/i.test(field)
                        ? "coupon"
                        : /bank/i.test(field)
                            ? "bank_offer"
                            : "offer"
                );
            }
        }

        return result;
    };

    const mergeOffers = (
        target,
        incoming
    ) => {
        const seen =
            new Set(target.map(offerKey));

        for (const offer of incoming || []) {
            const key =
                offerKey(offer);

            if (!seen.has(key)) {
                seen.add(key);
                target.push(offer);
            }
        }

        return target;
    };

    const parseOfferText = value => {
        const offers = [];

        const lines = String(value || "")
            .split(/\n+/)
            .map(line =>
                line.replace(/\s+/g, " ").trim()
            )
            .filter(Boolean);

        for (const line of lines) {
            const coupon =
                /coupon|promo code|use code|apply code/i
                    .test(line);

            const bankOrCard =
                /bank|credit card|debit card|cashback|instant discount|emi|visa|mastercard|rupay|amex/i
                    .test(line);

            if (!coupon && !bankOrCard) {
                continue;
            }

            const percent =
                line.match(/(\d+(?:\.\d+)?)\s*%/);

            const amount =
                line.match(/₹\s*([\d,]+)/i);

            const minimum =
                line.match(
                    /(?:minimum|min(?:imum)?\s*(?:transaction|spend|order)|orders?\s*(?:above|over))[^₹\d]{0,25}₹?\s*([\d,]+)/i
                );

            const maximum =
                line.match(
                    /(?:maximum|max(?:imum)\s*discount|up\s*to|upto)[^₹\d]{0,25}₹?\s*([\d,]+)/i
                );

            const code =
                line.match(
                    /(?:coupon|promo)?\s*(?:code|use)\s*[:\-]?\s*([A-Z0-9]{4,})/i
                );

            const issuer =
                (
                    line.match(
                        /\b(HDFC|SBI|ICICI|Axis|Kotak|IndusInd|Yes Bank|IDFC|RBL|HSBC|Bank of Baroda|Flipkart Axis)\b(?:\s+Bank)?/i
                    ) || []
                )[0] || "";

            const cardType =
                (
                    line.match(
                        /\b(credit card|debit card|credit\/debit card|card EMI|EMI)\b/i
                    ) || []
                )[0] || "";

            const offer = {
                kind: coupon
                    ? "coupon"
                    : "bank_offer",

                code: code
                    ? safeCode(code[1])
                    : "",

                title: safeText(line),
                description: safeText(line),
                issuer: safeText(issuer),
                card_type: safeText(cardType),
                payment_network: "",

                discount_percent: percent
                    ? Number(percent[1])
                    : null,

                discount_amount: amount
                    ? Number(
                        amount[1].replace(/,/g, "")
                    )
                    : null,

                minimum_transaction_amount: minimum
                    ? Number(
                        minimum[1].replace(/,/g, "")
                    )
                    : null,

                maximum_discount: maximum
                    ? Number(
                        maximum[1].replace(/,/g, "")
                    )
                    : null,

                validity: "",
                terms_url: ""
            };

            if (
                offer.title ||
                offer.description ||
                offer.issuer
            ) {
                offers.push(offer);
            }
        }

        return offers;
    };

        function extractPdpFromHtml(html) {
        if (!html || typeof html !== "string") return null;
        const idx = html.indexOf("window.__myx");
        if (idx === -1) return null;
        const startIdx = html.indexOf("{", idx);
        if (startIdx === -1) return null;
        const scriptEnd = html.indexOf("</script>", startIdx);
        const block = scriptEnd !== -1 ? html.substring(startIdx, scriptEnd) : html.substring(startIdx);
        const trimmed = block.trim().replace(/;$/, "");
        try {
            const parsed = JSON.parse(trimmed);
            if (parsed && parsed.pdpData) return parsed.pdpData;
        } catch (e) {
            let depth = 0;
            let endIdx = -1;
            for (let i = 0; i < trimmed.length; i++) {
                if (trimmed[i] === "{") depth++;
                else if (trimmed[i] === "}") {
                    depth--;
                    if (depth === 0) { endIdx = i; break; }
                }
            }
            if (endIdx !== -1) {
                try {
                    const sub = trimmed.substring(0, endIdx + 1);
                    const parsed = JSON.parse(sub);
                    if (parsed && parsed.pdpData) return parsed.pdpData;
                } catch (_) {}
            }
        }
        return null;
    }

    const enrichProductFromPdp = async (url, couponData = null, basePrice = 0, baseMrp = 0) => {
        if (!url) {
            return { offers: [], pdpSizes: null };
        }

        try {
            log("Fetching PDP data:", url);

            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    accept: "text/html,application/xhtml+xml,application/json"
                }
            });

            if (!response.ok) {
                log("PDP fetch HTTP error:", response.status, url);
                return { offers: [], pdpSizes: null };
            }

            const html = await response.text();
            const pdpData = extractPdpFromHtml(html);
            const offers = [];
            let pdpSizes = null;

            if (pdpData) {
                // 1. Extract Real Sizes from PDP
                if (Array.isArray(pdpData.sizes) && pdpData.sizes.length > 0) {
                    pdpSizes = pdpData.sizes.map(s => {
                        const stockCnt = s.selectedSeller?.sellableInventoryCount ||
                                         s.sizeSellerData?.[0]?.sellableInventoryCount ||
                                         (s.available ? 1 : 0);
                        const price = Number(s.selectedSeller?.discountedPrice || pdpData.price?.discounted || pdpData.price?.mrp || pdpData.mrp || basePrice || 0);
                        const mrp = Number(s.selectedSeller?.mrp || pdpData.price?.mrp || pdpData.mrp || baseMrp || 0);
                        return {
                            size: text(s.label) || "One Size",
                            sku: text(s.skuId) || "",
                            available: Boolean(s.available),
                            quantity: stockCnt,
                            stock: stockCnt,
                            price,
                            mrp
                        };
                    });
                }

                // 2. Extract Bank & EMI Offers from PDP
                for (const raw of (pdpData.offers || [])) {
                    const type = String(raw.type || "offer").toUpperCase();
                    const title = safeText(raw.title);
                    const desc = safeText(raw.description);
                    const combined = `${title} ${desc}`;

                    const pctMatch = combined.match(/(\d+(?:\.\d+)?)\s*%/);
                    const minMatch = combined.match(/(?:min\s*spend|min\s*transaction|mov\s*of|orders\s*above)\s*₹?\s*([\d,]+)/i);
                    const maxMatch = combined.match(/(?:max\s*discount|upto|up\s*to)\s*₹?\s*([\d,]+)/i);

                    let issuer = "";
                    for (const b of ["HDFC", "SBI", "ICICI", "Axis", "Kotak", "IndusInd", "IDFC", "RBL", "HSBC", "Flipkart Axis"]) {
                        if (new RegExp("\\b" + b + "\\b", "i").test(combined)) {
                            issuer = b;
                            break;
                        }
                    }

                    offers.push({
                        kind: type === "BANK" ? "bank_offer" : (type === "EMI" ? "emi" : "offer"),
                        code: "",
                        title,
                        description: desc,
                        issuer,
                        card_type: /credit\s*card/i.test(combined) ? "Credit Card" : (/debit\s*card/i.test(combined) ? "Debit Card" : ""),
                        payment_network: "",
                        discount_percent: pctMatch ? Number(pctMatch[1]) : null,
                        discount_amount: null,
                        minimum_transaction_amount: minMatch ? Number(minMatch[1].replace(/,/g, "")) : null,
                        maximum_discount: maxMatch ? Number(maxMatch[1].replace(/,/g, "")) : null,
                        validity: "",
                        terms_url: raw.action ? String(raw.action) : ""
                    });
                }
            }

            // Fallback: parse offers from HTML DOM if pdpData.offers was empty
            if (offers.length === 0) {
                const document = new DOMParser().parseFromString(html, "text/html");
                mergeOffers(offers, parseOfferText(document.body ? document.body.innerText : ""));
            }

            // 3. Add Coupon Offer from search couponData
            if (couponData) {
                const code = safeCode(couponData.couponDescription?.couponCode || couponData.couponCode || "");
                const disc = number(couponData.couponDiscount) || 0;
                const desc = safeText(couponData.couponDescription?.description || couponData.description || "");
                if (code || disc > 0) {
                    offers.push({
                        kind: "coupon",
                        code: code || "BFFSAVE",
                        title: code ? `${code}: ₹${disc} Off` : `Flat ₹${disc} Coupon Discount`,
                        description: desc || `Extra ₹${disc} off with coupon`,
                        issuer: "Myntra",
                        card_type: "",
                        payment_network: "",
                        discount_percent: null,
                        discount_amount: disc,
                        minimum_transaction_amount: null,
                        maximum_discount: disc,
                        validity: "",
                        terms_url: couponData.tagLink ? String(couponData.tagLink) : ""
                    });
                }
            }

            // 4. Product discount on MRP
            const mrp = Number(pdpData?.price?.mrp || pdpData?.mrp || baseMrp || 0);
            const price = Number(pdpData?.price?.discounted || pdpData?.discountedPrice || basePrice || mrp);
            if (mrp > price && price > 0) {
                const discPct = Math.round(((mrp - price) / mrp) * 100);
                offers.push({
                    kind: "discount",
                    code: "MRP_DISCOUNT",
                    title: `${discPct}% Off on MRP`,
                    description: `Flat ₹${mrp - price} off on MRP`,
                    issuer: "Columbia",
                    card_type: "",
                    payment_network: "",
                    discount_percent: discPct,
                    discount_amount: mrp - price,
                    minimum_transaction_amount: null,
                    maximum_discount: mrp - price,
                    validity: "",
                    terms_url: ""
                });
            }

            return { offers, pdpSizes };
        } catch (error) {
            log("PDP extraction error:", error.message, url);
            return { offers: [], pdpSizes: null };
        }
    };

    const extractProductOffers = async url => {
        const { offers } = await enrichProductFromPdp(url);
        return offers;
    };

    const fetchSearchPage = async (
        currentPage,
        currentContext
    ) => {
        const offset =
            currentPage === 1
                ? 0
                : ((currentPage - 1) * ROWS) - 1;

        const url =
            `/gateway/v4/search/columbia` +
            `?rawQuery=columbia` +
            `&rows=${ROWS}` +
            `&o=${offset}` +
            `&plaEnabled=true` +
            `&xdEnabled=false` +
            `&isFacet=true` +
            `&p=${currentPage}`;

        const headers = {
            accept: "application/json"
        };

        if (currentContext) {
            headers["pagination-context"] =
                currentContext;
        }

        log(
            `Fetching search page ${currentPage}`,
            `offset=${offset}`
        );

        const response =
            await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                headers
            });

        if (!response.ok) {
            throw new Error(
                `Search HTTP ${response.status}`
            );
        }

        const data =
            await response.json();

        const count =
            data?.products?.length ||
            data?.results?.products?.length ||
            data?.searchData?.results?.products?.length ||
            0;

        log(
            `Search page ${currentPage} complete`,
            `${count} products`
        );

        return {
            data,
            paginationContext:
                response.headers.get(
                    "pagination-context"
                )
        };
    };

    log("Starting Myntra Columbia scraper");

    while (true) {
        let result;

        try {
            result =
                await fetchSearchPage(
                    page,
                    paginationContext
                );
        } catch (error) {
            log(
                `Scraping stopped on page ${page}:`,
                error.message
            );

            break;
        }

        paginationContext =
            result.paginationContext ||
            paginationContext;

        const data =
            result.data;

        const pageProducts =
            data?.products ||
            data?.results?.products ||
            data?.searchData?.results?.products ||
            [];

        const totalPages =
            Math.max(
                1,
                Math.ceil(
                    Number(data.totalCount || 0) /
                    ROWS
                )
            );

        for (const product of pageProducts) {
            const productId =
                String(
                    product.productId ||
                    product.id ||
                    ""
                );

            if (!productId) {
                continue;
            }

            const invMap = new Map();
            if (Array.isArray(product.inventoryInfo)) {
                for (const inv of product.inventoryInfo) {
                    if (inv && inv.label) invMap.set(String(inv.label).trim(), inv);
                }
            }

            let entries = [];
            const rawSizesStr = String(product.sizes || "").trim();
            if (rawSizesStr) {
                const sizeLabels = rawSizesStr.split(",").map(s => s.trim()).filter(Boolean);
                for (const lbl of sizeLabels) {
                    const matchedInv = invMap.get(lbl);
                    entries.push({
                        label: lbl,
                        skuId: matchedInv?.skuId ? String(matchedInv.skuId) : "",
                        available: matchedInv ? Boolean(matchedInv.available) : true,
                        quantity: matchedInv?.inventory != null ? matchedInv.inventory : (matchedInv?.available ? 1 : null)
                    });
                }
            } else if (Array.isArray(product.inventoryInfo) && product.inventoryInfo.length > 0) {
                entries = product.inventoryInfo.map(inventoryRecord);
            } else {
                entries = [{ label: "One Size", skuId: "", available: true, quantity: 1 }];
            }

            const url =
                product.landingPageUrl
                    ? `https://www.myntra.com/${product.landingPageUrl.replace(/^\/+/, "")}`
                    : "";

            for (const size of entries) {
                products.push({
                    product_id: productId,
                    source: "myntra",

                    title:
                        product.productName ||
                        product.name ||
                        "",

                    size: size.label,

                    color:
                        product.primaryColour ||
                        product.color ||
                        product.colorName ||
                        "",

                    variant_id:
                        size.skuId ||
                        product.variantId ||
                        product.sku ||
                        "",

                    available:
                        size.available,

                    quantity:
                        size.quantity,

                    price:
                        Number(
                            product.discountedPrice ??
                            product.price ??
                            product.mrp ??
                            0
                        ) || 0,

                    mrp:
                        Number(
                            product.mrp ??
                            product.price ??
                            product.discountedPrice ??
                            0
                        ) || 0,

                    url,

                    image_url:
                        product.searchImage ||
                        product.image ||
                        "",

                    coupon_data: product.couponData || null,
                    offers: []
                });
            }
        }

        log(
            `Page ${page}/${totalPages} finished`,
            `records=${products.length}`
        );

        updateProgress(
            "Collecting products",
            page,
            totalPages,
            {
                records: products.length
            }
        );

        if (
            data.hasNextPage === false ||
            pageProducts.length === 0 ||
            page >= totalPages ||
            page >= 100 ||
            (window.__MAX_PAGES__ && page >= window.__MAX_PAGES__)
        ) {
            log("No more search pages");
            break;
        }

        page++;

        log(
            `Waiting before page ${page}`
        );

        await sleep(1500);
    }

    const urlMap = new Map();
    for (const p of products) {
        if (p.url && !urlMap.has(p.url)) {
            urlMap.set(p.url, { couponData: p.coupon_data, price: p.price, mrp: p.mrp, productId: p.product_id });
        }
    }

    const urls = [...urlMap.keys()];
    log("Starting offer & variant enrichment", `pages=${urls.length}`);

    const enrichedProducts = [];

    for (let index = 0; index < urls.length; index++) {
        const url = urls[index];
        const meta = urlMap.get(url);
        const { offers, pdpSizes } = await enrichProductFromPdp(url, meta.couponData, meta.price, meta.mrp);

        offerCache.set(url, offers);

        const matching = products.filter(p => p.url === url);
        if (!matching.length) continue;
        const base = matching[0];

        if (Array.isArray(pdpSizes) && pdpSizes.length > 0) {
            for (const sz of pdpSizes) {
                enrichedProducts.push({
                    product_id: base.product_id,
                    source: "myntra",
                    title: base.title,
                    size: sz.size,
                    color: base.color,
                    variant_id: sz.sku || base.variant_id,
                    available: sz.available,
                    quantity: sz.quantity,
                    price: sz.price || base.price,
                    mrp: sz.mrp || base.mrp,
                    url: base.url,
                    image_url: base.image_url,
                    offers: offers
                });
            }
        } else {
            for (const m of matching) {
                m.offers = offers;
                enrichedProducts.push(m);
            }
        }

        log(`Enriched product ${index + 1}/${urls.length}`, `sizes=${pdpSizes ? pdpSizes.length : matching.length}`, `offers=${offers.length}`);
        updateProgress("Enriching products & offers", index + 1, urls.length, {
            processed: index + 1,
            total: urls.length,
            offers: offers.length
        });
        await sleep(150);
    }

    const finalProducts = enrichedProducts.length > 0 ? enrichedProducts : products;

    const uniqueProducts = [
        ...new Map(
            finalProducts.map(product => [
                [
                    product.product_id,
                    product.size,
                    product.color,
                    product.variant_id
                ].join("|"),
                product
            ])
        ).values()
    ];

    window.__MYNTRA_PRODUCTS__ = uniqueProducts;

    window.enrichProductFromPdp = enrichProductFromPdp;
    window.__MYNTRA_SCRAPER_DONE__ =
        true;

    log(
        "Myntra scraper completed",
        {
            records: uniqueProducts.length,
            pages: page,
            offer_count:
                uniqueProducts.reduce(
                    (total, product) =>
                        total +
                        product.offers.length,
                    0
                )
        }
    );

    window.downloadMyntraJSON =
        function () {
            log("Starting JSON export");

            const source =
                window.__MYNTRA_PRODUCTS__ || [];

            const payload = {
                schema_version: 2,
                source: "myntra",
                scraped_at:
                    new Date().toISOString(),
                record_count:
                    source.length,
                products: source
            };

            const json =
                JSON.stringify(
                    payload
                );

            log(
                "JSON serialization completed",
                {
                    records: source.length,
                    characters: json.length
                }
            );

            const blob =
                new Blob(
                    [json],
                    {
                        type: "application/json"
                    }
                );

            const blobUrl =
                URL.createObjectURL(blob);

            const link =
                document.createElement("a");

            link.href =
                blobUrl;

            link.download =
                `myntra_columbia_products_${source.length}.json`;

            document.body.appendChild(link);
            link.click();
            link.remove();

            setTimeout(
                () =>
                    URL.revokeObjectURL(blobUrl),
                10000
            );

            log(
                "JSON download triggered successfully"
            );
        };

    log(
        "Run downloadMyntraJSON() to export the data"
    );
})();