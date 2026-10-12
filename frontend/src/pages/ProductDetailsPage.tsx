import React, { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  RotateCw,
  ExternalLink,
  Maximize2,
  Tag,
  CheckCircle2,
  AlertCircle,
  Package,
  Layers,
  Percent,
  Check,
} from "lucide-react";
import productService from "../services/productService";
import { ProductFamily, PlatformListing, ProductVariant, ProductOffer } from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

export const ProductDetailsPage: React.FC = () => {
  const { familyId } = useParams<{ familyId: string }>();
  const [product, setProduct] = useState<ProductFamily | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // User selections
  const [selectedImage, setSelectedImage] = useState<string>("");
  const [selectedPlatformKey, setSelectedPlatformKey] = useState<string>("columbia");
  const [selectedOfferModal, setSelectedOfferModal] = useState<ProductOffer | null>(null);

  useEffect(() => {
    if (familyId) {
      loadProduct(familyId);
    }
  }, [familyId]);

  const loadProduct = async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await productService.getProductDetails(id);
      setProduct(data);
      setSelectedImage(data.image_url || "");
      // Default to first platform that has active price or listing
      const firstActive = data.platforms.find((p) => p.price !== null && p.price !== undefined);
      if (firstActive) {
        setSelectedPlatformKey(firstActive.platform);
      } else if (data.platforms.length > 0) {
        setSelectedPlatformKey(data.platforms[0].platform);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load product details.");
    } finally {
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-8 py-20 text-center space-y-3">
        <div className="w-10 h-10 border-3 border-sky-200 border-t-sky-500 rounded-full animate-spin mx-auto" />
        <p className="text-sm font-semibold text-slate-600">Gathering 7-platform intelligence...</p>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-8 py-20 text-center space-y-4">
        <div className="bg-rose-50 text-rose-700 p-6 rounded-2xl border border-rose-200 max-w-md mx-auto">
          <p className="font-bold text-base mb-1">Product Not Found</p>
          <p className="text-xs text-rose-600">{error || "Could not retrieve product family details."}</p>
          <Link
            to="/home"
            className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 bg-rose-600 text-white rounded-xl text-xs font-bold"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Return to Search</span>
          </Link>
        </div>
      </div>
    );
  }

  // Thumbnails gallery
  const allImages = Array.from(
    new Set([product.image_url, ...product.gallery_images].filter(Boolean) as string[])
  );

  // Active selected platform listing
  const activeListing: PlatformListing =
    product.platforms.find((p) => p.platform === selectedPlatformKey) || product.platforms[0];

  // Active platform variants list: fallback to family variants if platform-level variants empty
  const activeVariants: ProductVariant[] =
    activeListing.variants && activeListing.variants.length > 0
      ? activeListing.variants
      : activeListing.price !== null
      ? (product.variants || [])
      : [];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-8 py-6 space-y-8">
      {/* Top Navigation & Status Bar */}
      <div className="flex items-center justify-between gap-4">
        <Link
          to="/home"
          className="inline-flex items-center gap-2 text-xs sm:text-sm font-semibold text-slate-600 hover:text-sky-600 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>Back to search</span>
        </Link>

        <div className="flex items-center gap-2 text-xs text-slate-500 font-medium">
          <span>Last updated: {product.data_freshness || "12 Oct 2026, 05:30 PM"}</span>
          <button
            onClick={() => loadProduct(product.family_id)}
            className="p-1 hover:text-sky-600 transition-colors cursor-pointer"
            title="Refresh snapshot"
          >
            <RotateCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Top 2-Part Section: Left Gallery (5 cols) & Right Details with Platform Selector (7 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 bg-white p-6 sm:p-8 rounded-3xl border border-slate-200/90 shadow-sm">
        {/* Left Column (lg: 5 cols): All Images & Main Preview for Selected Platform */}
        <div className="lg:col-span-5 flex flex-col-reverse sm:flex-row gap-4">
          {/* Vertical Thumbnail Strip */}
          <div className="flex sm:flex-col gap-2 shrink-0 overflow-x-auto sm:overflow-visible">
            {allImages.slice(0, 5).map((img, idx) => (
              <button
                key={idx}
                onClick={() => setSelectedImage(img)}
                className={`w-14 h-14 rounded-xl border p-1 bg-slate-50 overflow-hidden transition-all ${
                  (selectedImage || activeListing.image_url || product.image_url) === img
                    ? "border-sky-500 ring-2 ring-sky-200"
                    : "border-slate-200 hover:border-slate-300 opacity-80 hover:opacity-100"
                }`}
              >
                <img
                  src={img}
                  alt={`Thumb ${idx + 1}`}
                  className="w-full h-full object-contain mix-blend-multiply"
                />
              </button>
            ))}
          </div>

          {/* Large Main Preview */}
          <div className="relative flex-1 bg-slate-50/70 rounded-2xl border border-slate-100 p-6 flex items-center justify-center min-h-[320px]">
            <img
              src={selectedImage || activeListing.image_url || product.image_url || "/vantis_logo.png"}
              alt={activeListing.listing_title || product.title}
              className="max-h-[320px] w-full object-contain mix-blend-multiply transition-all hover:scale-105"
            />
            <button
              onClick={() => window.open(selectedImage || activeListing.image_url || product.image_url || "", "_blank")}
              className="absolute bottom-3 right-3 p-2 rounded-xl bg-white/90 border border-slate-200 text-slate-500 hover:text-slate-900 shadow-xs cursor-pointer"
              title="Expand full image"
            >
              <Maximize2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Right Column (lg: 7 cols): Platform Selector, Dynamic Title, Identifiers, Pricing */}
        <div className="lg:col-span-7 space-y-5">
          {/* PLATFORM SELECTOR (Top Tile Platform Option) */}
          <div className="space-y-2.5">
            <div className="flex items-center justify-between text-xs font-bold text-slate-700">
              <span className="uppercase tracking-wider text-[11px] text-slate-500 font-extrabold">
                Select Platform For Data
              </span>
              <span className="text-slate-400 font-normal">
                {product.platforms.filter((p) => p.price !== null).length} of 7 platforms available
              </span>
            </div>

            {/* Platform Selection Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {product.platforms.map((plat) => {
                const isSelected = selectedPlatformKey === plat.platform;
                const isAvailable = plat.price !== null && plat.price !== undefined;

                return (
                  <button
                    key={plat.platform}
                    type="button"
                    onClick={() => {
                      setSelectedPlatformKey(plat.platform);
                      if (plat.image_url) {
                        setSelectedImage(plat.image_url);
                      }
                    }}
                    className={`p-2.5 rounded-2xl border text-left transition-all cursor-pointer flex flex-col justify-between gap-1.5 ${
                      isSelected
                        ? "bg-sky-50/70 border-sky-400 ring-2 ring-sky-200 shadow-xs"
                        : isAvailable
                        ? "bg-white border-slate-200 hover:border-slate-300 hover:bg-slate-50/50 shadow-2xs"
                        : "bg-slate-50/60 border-slate-200/60 opacity-60 hover:opacity-90"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <PlatformLogo platform={plat.platform} size="sm" showLabel={false} />
                      {isSelected && (
                        <span className="w-4 h-4 rounded-full bg-sky-500 text-white flex items-center justify-center">
                          <Check className="w-2.5 h-2.5 stroke-[3]" />
                        </span>
                      )}
                    </div>
                    <div>
                      <div className="font-extrabold text-xs text-slate-900 truncate">
                        {plat.platform_name}
                      </div>
                      <div className="flex items-center gap-1.5 mt-0.5 text-[11px]">
                        <span
                          className={`w-1.5 h-1.5 rounded-full ${
                            isAvailable
                              ? plat.availability_status === "In stock"
                                ? "bg-emerald-500"
                                : plat.availability_status === "Limited stock"
                                ? "bg-amber-500"
                                : "bg-rose-500"
                              : "bg-slate-300"
                          }`}
                        />
                        <span className={`font-semibold ${isAvailable ? "text-slate-700" : "text-slate-400"}`}>
                          {isAvailable ? `₹${plat.price?.toLocaleString("en-IN")}` : "No data"}
                        </span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Dynamic Platform Title */}
          <div className="space-y-1 pt-1">
            <div className="inline-flex items-center gap-1.5 text-xs font-bold text-sky-600 uppercase tracking-wider">
              <span>{activeListing.platform_name} Listing Details</span>
            </div>
            <h1 className="text-xl sm:text-2xl font-black text-slate-900 tracking-tight leading-snug">
              {activeListing.listing_title || product.title}
            </h1>
          </div>

          {/* Platform-Specific Identifier Row */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500 font-mono py-2 border-y border-slate-100">
            {activeListing.product_id && (
              <span>
                {selectedPlatformKey === "amazon" ? "ASIN" : `${activeListing.platform_name} ID`}:{" "}
                <span className="font-bold text-slate-900">{activeListing.product_id}</span>
              </span>
            )}
            {activeListing.product_id && product.style && <span className="text-slate-200">|</span>}
            {product.style && (
              <span>
                Style: <span className="font-semibold text-slate-800">{product.style}</span>
              </span>
            )}
            {product.ean && (
              <>
                <span className="text-slate-200">|</span>
                <span>
                  EAN: <span className="font-semibold text-slate-800">{product.ean}</span>
                </span>
              </>
            )}
            <span className="text-slate-200">|</span>
            <span>
              Category: <span className="font-semibold text-slate-800">{product.category}</span>
            </span>
            <span className="text-slate-200">|</span>
            <span>
              Gender: <span className="font-semibold text-slate-800">{product.gender}</span>
            </span>
          </div>

          {/* Selected Platform Pricing & Availability Banner */}
          <div className="p-4 bg-slate-50/80 rounded-2xl border border-slate-200/80 flex flex-wrap items-center justify-between gap-4">
            <div>
              <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider block">
                {activeListing.platform_name} Price
              </span>
              <div className="flex items-baseline gap-3 mt-0.5">
                <span className="text-2xl sm:text-3xl font-black text-slate-900">
                  {activeListing.price != null ? `₹${activeListing.price.toLocaleString("en-IN")}` : "—"}
                </span>
                {(activeListing.mrp || product.mrp) && (
                  <span className="text-xs font-bold text-slate-400">
                    MRP: ₹{(activeListing.mrp || product.mrp)?.toLocaleString("en-IN")}
                  </span>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span
                className={`px-3 py-1 rounded-full text-xs font-bold border ${
                  activeListing.availability_status === "In stock"
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : activeListing.availability_status === "Limited stock"
                    ? "bg-amber-50 text-amber-700 border-amber-200"
                    : activeListing.availability_status === "Out of stock"
                    ? "bg-rose-50 text-rose-700 border-rose-200"
                    : "bg-slate-100 text-slate-500 border-slate-200"
                }`}
              >
                {activeListing.availability_status}
              </span>
            </div>
          </div>

          {/* Tags */}
          <div className="flex flex-wrap gap-1.5">
            {product.tags.map((tag, idx) => (
              <span
                key={idx}
                className="bg-sky-50 text-sky-700 text-xs font-semibold px-2.5 py-0.5 rounded-full border border-sky-100"
              >
                {tag}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* Bottom Section: Full Variants, Sizes, Stock, Price & Offers for Selected Platform */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-sm overflow-hidden space-y-6 p-6 sm:p-8">
        {/* Selected Platform Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-slate-100">
          <div className="flex items-center gap-3">
            <PlatformLogo platform={activeListing.platform} size="lg" showLabel={false} />
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-black text-slate-900 tracking-tight">
                  {activeListing.platform_name} Catalog Intelligence
                </h2>
                <span
                  className={`text-[11px] font-bold px-2 py-0.5 rounded-full border ${
                    activeListing.price !== null
                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                      : "bg-slate-100 text-slate-500 border-slate-200"
                  }`}
                >
                  {activeListing.availability_status}
                </span>
              </div>
              <p className="text-xs text-slate-500 font-medium mt-0.5">
                Scraped variants, inventory levels, and promotional discounts for {activeListing.platform_name}
              </p>
            </div>
          </div>

          {activeListing.url && activeListing.price !== null && (
            <a
              href={activeListing.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold rounded-xl transition-all shadow-2xs self-start sm:self-auto cursor-pointer"
            >
              <span>View On {activeListing.platform_name}</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          )}
        </div>

        {activeListing.availability_status === "No data available" ? (
          <div className="py-12 text-center space-y-3">
            <div className="w-12 h-12 rounded-2xl bg-slate-50 border border-slate-200 text-slate-400 flex items-center justify-center mx-auto">
              <Package className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <h3 className="font-extrabold text-base text-slate-800">
                No Data Available on {activeListing.platform_name}
              </h3>
              <p className="text-xs text-slate-400 max-w-sm mx-auto">
                This product is not currently listed or active on {activeListing.platform_name}. Select another platform above to inspect listings, variants, and offers.
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* OFFERS SECTION (Promo codes, bank discounts, EMI options from JSON) */}
            {activeListing.offers && activeListing.offers.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Tag className="w-4 h-4 text-sky-500" />
                  <h3 className="font-extrabold text-sm text-slate-900 uppercase tracking-wider text-[11px]">
                    Available Platform Offers &amp; Discounts ({activeListing.offers.length})
                  </h3>
                </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {activeListing.offers.map((off, oidx) => (
                <div
                  key={oidx}
                  onClick={() => setSelectedOfferModal(off)}
                  className="p-3.5 bg-slate-50/80 hover:bg-sky-50/40 rounded-2xl border border-slate-200/90 transition-all cursor-pointer space-y-1.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-bold text-xs text-slate-900 line-clamp-1">
                      {off.title || "Special Promotion"}
                    </span>
                    {off.code && (
                      <span className="font-mono text-[10px] font-bold bg-white text-sky-700 border border-sky-200 px-2 py-0.5 rounded-md shrink-0">
                        {off.code}
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-500 line-clamp-2">
                    {off.description || off.issuer || "Special discount at checkout."}
                  </p>
                  {(off.discount_amount || off.discount_percent || off.offer_price) && (
                    <div className="text-[11px] font-bold text-emerald-600 pt-0.5">
                      {off.discount_amount && `Flat ₹${off.discount_amount} Off`}
                      {off.discount_percent && `${off.discount_percent}% Instant Discount`}
                      {off.offer_price && `Effective Price: ₹${off.offer_price.toLocaleString("en-IN")}`}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* VARIANTS & SIZES STOCK TABLE */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-sky-500" />
              <h3 className="font-extrabold text-sm text-slate-900 uppercase tracking-wider text-[11px]">
                Variant-Level Inventory &amp; Size Breakdown
              </h3>
            </div>
            <span className="text-xs font-semibold text-slate-400">
              {activeVariants.length > 0 ? `${activeVariants.length} variants listed` : "1 standard listing"}
            </span>
          </div>

          <div className="overflow-x-auto rounded-2xl border border-slate-200/90">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50/80 border-b border-slate-200 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                  <th className="py-3 px-4">Size</th>
                  <th className="py-3 px-4">Variant / Color</th>
                  <th className="py-3 px-4">SKU / Identifier</th>
                  <th className="py-3 px-4">Stock &amp; Availability</th>
                  <th className="py-3 px-4">Price</th>
                  <th className="py-3 px-4">MRP</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-medium text-slate-700">
                {activeVariants.length > 0 ? (
                  activeVariants.map((v, vidx) => {
                    const isAvailable = v.available !== false;
                    const stockVal = v.stock ?? v.quantity;

                    return (
                      <tr key={vidx} className="hover:bg-slate-50/60 transition-colors">
                        {/* Size */}
                        <td className="py-3.5 px-4 font-bold text-slate-900">
                          <span className="inline-block px-2.5 py-1 bg-slate-100 rounded-lg text-xs font-mono font-bold">
                            {v.size || "Standard"}
                          </span>
                        </td>

                        {/* Color / Variant */}
                        <td className="py-3.5 px-4 font-semibold text-slate-800">
                          {v.color || product.title}
                        </td>

                        {/* SKU */}
                        <td className="py-3.5 px-4 font-mono text-[11px] text-slate-500">
                          {v.sku || v.ean || product.style || "—"}
                        </td>

                        {/* Stock & Availability */}
                        <td className="py-3.5 px-4 whitespace-nowrap">
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`w-2 h-2 rounded-full ${
                                isAvailable ? "bg-emerald-500" : "bg-rose-400"
                              }`}
                            />
                            <span className={`font-bold ${isAvailable ? "text-emerald-700" : "text-rose-600"}`}>
                              {isAvailable ? "In stock" : "Out of stock"}
                            </span>
                            {stockVal && isAvailable && (
                              <span className="text-[11px] text-slate-400 font-normal">
                                ({typeof stockVal === "number" ? `${stockVal} units` : stockVal})
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Price */}
                        <td className="py-3.5 px-4 font-extrabold text-slate-900">
                          {v.price ? `₹${v.price.toLocaleString("en-IN")}` : activeListing.price ? `₹${activeListing.price.toLocaleString("en-IN")}` : "—"}
                        </td>

                        {/* MRP */}
                        <td className="py-3.5 px-4 font-mono text-slate-500">
                          {v.mrp ? `₹${v.mrp.toLocaleString("en-IN")}` : product.mrp ? `₹${product.mrp.toLocaleString("en-IN")}` : "—"}
                        </td>

                        {/* Action */}
                        <td className="py-3.5 px-4 text-right">
                          <a
                            href={v.url || activeListing.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition-all cursor-pointer"
                          >
                            <span>View</span>
                            <ExternalLink className="w-3 h-3 text-slate-400" />
                          </a>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  /* Single listing fallback */
                  <tr>
                    <td className="py-4 px-4 font-bold text-slate-900">
                      <span className="px-2.5 py-1 bg-slate-100 rounded-lg text-xs font-mono font-bold">
                        {activeListing.sizes_summary || "Standard"}
                      </span>
                    </td>
                    <td className="py-4 px-4 font-semibold text-slate-800">
                      {activeListing.listing_title}
                    </td>
                    <td className="py-4 px-4 font-mono text-xs text-slate-500">
                      {product.style || product.sku || "—"}
                    </td>
                    <td className="py-4 px-4">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            activeListing.price !== null ? "bg-emerald-500" : "bg-slate-300"
                          }`}
                        />
                        <span className="font-bold text-slate-800">
                          {activeListing.availability_status}
                        </span>
                        {activeListing.stock_text && (
                          <span className="text-slate-400 font-normal">
                            ({activeListing.stock_text})
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-4 px-4 font-extrabold text-slate-900">
                      {activeListing.price ? `₹${activeListing.price.toLocaleString("en-IN")}` : "—"}
                    </td>
                    <td className="py-4 px-4 font-mono text-slate-500">
                      {product.mrp ? `₹${product.mrp.toLocaleString("en-IN")}` : "—"}
                    </td>
                    <td className="py-4 px-4 text-right">
                      {activeListing.url && activeListing.price !== null ? (
                        <a
                          href={activeListing.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold transition-all"
                        >
                          <span>View</span>
                          <ExternalLink className="w-3 h-3 text-slate-400" />
                        </a>
                      ) : (
                        <span className="text-slate-300 italic text-xs">Unlisted</span>
                      )}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </>
    )}
  </div>

      {/* Offer Modal */}
      {selectedOfferModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-2xl p-6 max-w-md w-full shadow-2xl border border-slate-200 space-y-4">
            <div className="flex justify-between items-start">
              <div className="flex items-center gap-2 text-sky-600 font-bold text-base">
                <Tag className="w-5 h-5" />
                <span>{selectedOfferModal.title}</span>
              </div>
              <button
                onClick={() => setSelectedOfferModal(null)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              {selectedOfferModal.description || "Promotion applicable directly at checkout."}
            </p>

            <div className="p-3 bg-slate-50 rounded-xl space-y-1.5 text-xs text-slate-600 border border-slate-100">
              {selectedOfferModal.code && (
                <div>
                  Coupon Code:{" "}
                  <span className="font-mono font-bold text-slate-900 bg-white px-2 py-0.5 rounded border border-slate-200">
                    {selectedOfferModal.code}
                  </span>
                </div>
              )}
              {selectedOfferModal.issuer && (
                <div>
                  Bank / Issuer:{" "}
                  <span className="font-semibold text-slate-800">{selectedOfferModal.issuer}</span>
                </div>
              )}
              {selectedOfferModal.minimum_transaction_amount && (
                <div>
                  Min Transaction:{" "}
                  <span className="font-semibold text-slate-800">
                    ₹{selectedOfferModal.minimum_transaction_amount}
                  </span>
                </div>
              )}
              {selectedOfferModal.maximum_discount && (
                <div>
                  Max Discount:{" "}
                  <span className="font-semibold text-slate-800">
                    ₹{selectedOfferModal.maximum_discount}
                  </span>
                </div>
              )}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setSelectedOfferModal(null)}
                className="px-4 py-2 bg-slate-100 hover:bg-slate-200 rounded-xl text-xs font-semibold text-slate-700 cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProductDetailsPage;
