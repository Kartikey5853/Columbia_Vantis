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

    const extractProductOffers = async url => {
        if (!url) {
            return [];
        }

        try {
            log("Fetching product offer page:", url);

            const response =
                await fetch(url, {
                    method: "GET",
                    credentials: "same-origin",
                    headers: {
                        accept:
                            "text/html,application/xhtml+xml"
                    }
                });

            if (!response.ok) {
                log(
                    "Offer page failed:",
                    response.status,
                    url
                );

                return [];
            }

            const html =
                await response.text();

            const document =
                new DOMParser().parseFromString(
                    html,
                    "text/html"
                );

            const offers = [];

            for (
                const script
                of document.querySelectorAll("script")
            ) {
                const raw =
                    (script.textContent || "").trim();

                if (
                    !raw ||
                    raw.length > 2000000
                ) {
                    continue;
                }

                try {
                    const parsed =
                        JSON.parse(raw);

                    mergeOffers(
                        offers,
                        normalizeOffers(parsed)
                    );
                } catch (_) {
                    // Ignore non-JSON scripts.
                }
            }

            mergeOffers(
                offers,
                parseOfferText(
                    document.body
                        ? document.body.innerText
                        : ""
                )
            );

            log(
                "Offers found:",
                offers.length,
                url
            );

            return offers;
        } catch (error) {
            log(
                "Offer extraction error:",
                error.message,
                url
            );

            return [];
        }
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
            `&p=${currentPage}` +
            `&pincode=${PINCODE}`;

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

            const sizes =
                Array.isArray(
                    product.inventoryInfo
                ) &&
                product.inventoryInfo.length
                    ? product.inventoryInfo.map(
                        inventoryRecord
                    )
                    : String(
                        product.sizes || ""
                    )
                        .split(",")
                        .map(size =>
                            inventoryRecord({
                                label: size.trim()
                            })
                        )
                        .filter(size =>
                            size.label
                        );

            const entries =
                sizes.length
                    ? sizes
                    : [
                        {
                            label: "",
                            skuId: "",
                            available: null,
                            quantity: null
                        }
                    ];

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
            page >= 100
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

    const urls = [
        ...new Set(
            products
                .map(product => product.url)
                .filter(Boolean)
        )
    ];

    log(
        "Starting offer extraction",
        `pages=${urls.length}`
    );

    for (
        let index = 0;
        index < urls.length;
        index++
    ) {
        const url =
            urls[index];

        const offers =
            await extractProductOffers(url);

        offerCache.set(
            url,
            offers
        );

        log(
            `Offer page ${index + 1}/${urls.length}`,
            `offers=${offers.length}`
        );

        updateProgress(
            "Extracting offers",
            index + 1,
            urls.length,
            {
                offers: offers.length
            }
        );

        await sleep(250);
    }

    for (const product of products) {
        product.offers =
            offerCache.get(product.url) || [];
    }

    const uniqueProducts = [
        ...new Map(
            products.map(product => [
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

    window.__MYNTRA_PRODUCTS__ =
        uniqueProducts;

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