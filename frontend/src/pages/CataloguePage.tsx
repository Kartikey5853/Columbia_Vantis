import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  RotateCcw,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  ExternalLink,
  ArrowRight,
  SlidersHorizontal,
  X,
  FileSpreadsheet,
  Tag,
} from "lucide-react";
import productService from "../services/productService";
import bundleService from "../services/bundleService";
import { ProductFamilySummary, PaginatedProductsResponse, PlatformListing } from "../types";
import PlatformLogo from "../components/brand/PlatformLogo";

export const CataloguePage: React.FC = () => {
  const navigate = useNavigate();

  // Data state
  const [products, setProducts] = useState<ProductFamilySummary[]>([]);
  const [totalRecords, setTotalRecords] = useState<number>(0);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [categories, setCategories] = useState<string[]>(["All"]);
  const [genders, setGenders] = useState<string[]>(["All"]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Filters & Pagination
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);
  const [jumpPage, setJumpPage] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState<string>("");
  const [category, setCategory] = useState<string>("All");
  const [gender, setGender] = useState<string>("All");
  const [priceRange, setPriceRange] = useState<string>("All");
  const [selectedRowIds, setSelectedRowIds] = useState<Set<string>>(new Set());
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  useEffect(() => {
    fetchProducts();
  }, [page, pageSize, category, gender, priceRange]);

  const fetchProducts = async (currentSearchTerm?: string, forceRefresh: boolean = false) => {
    setIsLoading(true);
    setFetchError(null);
    const searchToUse = currentSearchTerm !== undefined ? currentSearchTerm : searchTerm;

    let minPrice: number | undefined;
    let maxPrice: number | undefined;
    if (priceRange === "under_5k") {
      maxPrice = 5000;
    } else if (priceRange === "5k_10k") {
      minPrice = 5000;
      maxPrice = 10000;
    } else if (priceRange === "10k_15k") {
      minPrice = 10000;
      maxPrice = 15000;
    } else if (priceRange === "above_15k") {
      minPrice = 15000;
    }

    const isDefaultFilter =
      page === 1 &&
      pageSize === 10 &&
      !searchToUse &&
      category === "All" &&
      gender === "All" &&
      priceRange === "All";

    // Instant bootstrap via pre-warmed bundle ONLY when not forced refresh
    if (isDefaultFilter && !forceRefresh) {
      const cached = bundleService.getCachedBundle();
      if (cached && cached.catalog && cached.catalog.products?.length > 0) {
        setProducts(cached.catalog.products);
        setTotalRecords(cached.catalog.total_records);
        setTotalPages(cached.catalog.total_pages);
        if (cached.catalog.categories?.length) setCategories(cached.catalog.categories);
        if (cached.catalog.genders?.length) setGenders(cached.catalog.genders);
        setIsLoading(false);
        return;
      }
    }

    try {
      if (isDefaultFilter && !forceRefresh) {
        const bundle = await bundleService.getBundle();
        if (bundle && bundle.catalog && bundle.catalog.products?.length > 0) {
          setProducts(bundle.catalog.products);
          setTotalRecords(bundle.catalog.total_records);
          setTotalPages(bundle.catalog.total_pages);
          if (bundle.catalog.categories?.length) setCategories(bundle.catalog.categories);
          if (bundle.catalog.genders?.length) setGenders(bundle.catalog.genders);
          setIsLoading(false);
          return;
        }
      }

      const res: PaginatedProductsResponse = await productService.getProducts({
        page,
        page_size: pageSize,
        search: searchToUse || undefined,
        category: category !== "All" ? category : undefined,
        gender: gender !== "All" ? gender : undefined,
        min_price: minPrice,
        max_price: maxPrice,
      });

      setProducts(res.products || []);
      setTotalRecords(res.total_records || 0);
      setTotalPages(res.total_pages || 1);
      if (res.categories && res.categories.length > 0) setCategories(res.categories);
      if (res.genders && res.genders.length > 0) setGenders(res.genders);
    } catch (err: any) {
      console.error("Failed to fetch catalogue products:", err);
      setFetchError(err?.message || "Failed to load products. Please click refresh to retry.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefresh = async () => {
    bundleService.clearCache();
    await fetchProducts(undefined, true);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchProducts();
  };

  const handleExportExcel = async () => {
    setIsExporting(true);
    try {
      if (selectedRowIds.size > 0) {
        await productService.exportSelectedExcel(Array.from(selectedRowIds));
      } else {
        let minPrice: number | undefined;
        let maxPrice: number | undefined;
        if (priceRange === "under_5k") maxPrice = 5000;
        else if (priceRange === "5k_10k") { minPrice = 5000; maxPrice = 10000; }
        else if (priceRange === "10k_15k") { minPrice = 10000; maxPrice = 15000; }
        else if (priceRange === "above_15k") minPrice = 15000;

        await productService.exportCatalogExcel({
          search: searchTerm.trim() || undefined,
          category: category !== "All" ? category : undefined,
          gender: gender !== "All" ? gender : undefined,
          min_price: minPrice,
          max_price: maxPrice,
        });
      }
    } catch (err) {
      console.error("Excel export failed:", err);
    } finally {
      setIsExporting(false);
    }
  };

  const clearFilters = () => {
    setSearchTerm("");
    setCategory("All");
    setGender("All");
    setPriceRange("All");
    setPage(1);
    fetchProducts("");
  };

  const toggleSelectAll = () => {
    if (selectedRowIds.size === products.length) {
      setSelectedRowIds(new Set());
    } else {
      setSelectedRowIds(new Set(products.map((p) => p.family_id)));
    }
  };

  const toggleSelectRow = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const next = new Set(selectedRowIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedRowIds(next);
  };

  const toggleExpand = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedRowId(expandedRowId === id ? null : id);
  };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-8 py-8 space-y-6">
      {/* Title & Stats */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
              Product Catalogue
            </h1>
            <span className="bg-[#EAF6FE] text-[#079FE0] font-extrabold text-xs sm:text-sm px-3 py-1 rounded-full border border-sky-200">
              {totalRecords.toLocaleString("en-IN")} products
            </span>
          </div>
          <p className="text-xs sm:text-sm text-slate-500 font-medium">
            Browse all products from the master catalogue. Click on a row to view platform details or open the full product page.
          </p>
        </div>

        {/* Refresh Everything / Call back products */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading}
            className="inline-flex items-center gap-2 px-3.5 py-2 bg-white hover:bg-slate-50 active:bg-slate-100 disabled:opacity-50 text-slate-700 border border-slate-200/90 rounded-xl text-xs sm:text-sm font-bold shadow-2xs transition-all cursor-pointer"
            title="Refresh catalogue and reload all products from the server"
          >
            <RefreshCw className={`w-4 h-4 text-[#079FE0] ${isLoading ? "animate-spin" : ""}`} />
            <span>{isLoading ? "Refreshing..." : "Refresh Catalogue"}</span>
          </button>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="bg-white p-4 rounded-2xl border border-slate-200/90 shadow-2xs space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-center">
          {/* Search bar */}
          <div className="md:col-span-4 relative flex items-center">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearchSubmit(e)}
              placeholder="Search by name, SKU, EAN, ASIN, or style..."
              className="w-full pl-9 pr-8 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 transition-all font-medium"
            />
            {searchTerm && (
              <button
                type="button"
                onClick={() => {
                  setSearchTerm("");
                  setPage(1);
                  fetchProducts("");
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5 rounded cursor-pointer"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Category Dropdown */}
          <div className="md:col-span-2">
            <select
              value={category}
              onChange={(e) => {
                setCategory(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="All">Category: All</option>
              {categories.filter((c) => c !== "All").map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>

          {/* Gender Dropdown */}
          <div className="md:col-span-2">
            <select
              value={gender}
              onChange={(e) => {
                setGender(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="All">Gender: All</option>
              {genders.filter((g) => g !== "All").map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </div>

          {/* Export to Excel Button (Replaces platform filter as requested) */}
          <div className="md:col-span-2">
            <button
              type="button"
              onClick={handleExportExcel}
              disabled={isExporting}
              className="w-full py-2 px-3 bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 disabled:opacity-50 text-white rounded-xl text-xs font-bold transition-all shadow-xs flex items-center justify-center gap-1.5 cursor-pointer"
              title={selectedRowIds.size > 0 ? `Export ${selectedRowIds.size} selected products to Excel` : "Export catalogue to multi-sheet Excel"}
            >
              {isExporting ? (
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <FileSpreadsheet className="w-4 h-4 shrink-0" />
              )}
              <span>{isExporting ? "Exporting..." : selectedRowIds.size > 0 ? `Export (${selectedRowIds.size})` : "Export to Excel"}</span>
            </button>
          </div>

          {/* Price Range Dropdown */}
          <div className="md:col-span-1">
            <select
              value={priceRange}
              onChange={(e) => {
                setPriceRange(e.target.value);
                setPage(1);
              }}
              className="w-full py-2 px-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500/20 cursor-pointer"
            >
              <option value="All">Price: All</option>
              <option value="under_5k">&lt; ₹5,000</option>
              <option value="5k_10k">₹5K - ₹10K</option>
              <option value="10k_15k">₹10K - ₹15K</option>
              <option value="above_15k">&gt; ₹15,000</option>
            </select>
          </div>

          {/* Action Buttons: Refresh & Clear */}
          <div className="md:col-span-1 flex items-center justify-end gap-1.5">
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isLoading}
              className="p-2 text-slate-500 hover:text-[#079FE0] hover:bg-sky-50 rounded-xl transition-colors border border-slate-200 cursor-pointer disabled:opacity-50"
              title="Refresh catalogue and reload products from server"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`} />
            </button>
            <button
              type="button"
              onClick={clearFilters}
              className="p-2 text-slate-500 hover:text-rose-600 hover:bg-rose-50 rounded-xl transition-colors border border-slate-200 cursor-pointer"
              title="Clear all filters"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Error Banner if fetch failed */}
      {fetchError && (
        <div className="p-4 rounded-2xl bg-amber-50 border border-amber-200/80 text-amber-900 flex items-center justify-between gap-3 text-xs sm:text-sm">
          <div className="font-semibold">
            {fetchError}
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isLoading}
            className="px-3 py-1.5 bg-amber-600 hover:bg-amber-700 active:bg-amber-800 text-white rounded-xl font-bold transition-all shrink-0 cursor-pointer flex items-center gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Main Catalogue Table */}
      <div className="bg-white rounded-2xl border border-slate-200/90 shadow-2xs overflow-hidden flex flex-col">
        <div className="overflow-x-auto max-h-[560px] overflow-y-auto">
          <table className="w-full text-left border-collapse">
            <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur-xs shadow-2xs">
              <tr className="border-b border-slate-200 text-[11px] font-bold text-slate-500 uppercase tracking-wider">
                <th className="py-3 px-3 w-8">
                  <input
                    type="checkbox"
                    checked={selectedRowIds.size === products.length && products.length > 0}
                    onChange={toggleSelectAll}
                    className="w-4 h-4 text-sky-500 rounded focus:ring-sky-500"
                  />
                </th>
                <th className="py-3 px-2 w-10 text-center">#</th>
                <th className="py-3 px-3 w-16">Image</th>
                <th className="py-3 px-4">Product Name</th>
                <th className="py-3 px-4">Style / SKU</th>
                <th className="py-3 px-4">EAN</th>
                <th className="py-3 px-3">Category</th>
                <th className="py-3 px-3">Gender</th>
                <th className="py-3 px-3 text-center">Sizes</th>
                <th className="py-3 px-3 text-center">Platforms</th>
                <th className="py-3 px-4">Price / MRP</th>
                <th className="py-3 px-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
              {isLoading ? (
                <tr>
                  <td colSpan={12} className="py-20 text-center">
                    <div className="w-8 h-8 border-3 border-sky-200 border-t-sky-500 rounded-full animate-spin mx-auto mb-2" />
                    <span className="text-slate-400 font-semibold">Loading catalogue records...</span>
                  </td>
                </tr>
              ) : products.length === 0 ? (
                <tr>
                  <td colSpan={12} className="py-14 text-center text-slate-500">
                    <div className="max-w-md mx-auto space-y-3 px-4">
                      <p className="text-sm font-semibold text-slate-700">
                        {fetchError || "No products found or catalogue is not loaded yet."}
                      </p>
                      <p className="text-xs text-slate-400">
                        If the server was starting up or products haven't loaded into view, click below to refresh and load all products.
                      </p>
                      <button
                        type="button"
                        onClick={handleRefresh}
                        disabled={isLoading}
                        className="inline-flex items-center gap-2 px-4 py-2 bg-[#079FE0] hover:bg-[#068ec8] active:bg-[#057cb0] disabled:opacity-50 text-white rounded-xl text-xs font-bold transition-all shadow-xs cursor-pointer"
                      >
                        <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
                        <span>{isLoading ? "Loading Products..." : "Reload All Products"}</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ) : (
                products.map((product, idx) => {
                  const isSelected = selectedRowIds.has(product.family_id);
                  const isExpanded = expandedRowId === product.family_id;
                  const rowNumber = (page - 1) * pageSize + idx + 1;

                  return (
                    <React.Fragment key={product.family_id}>
                      <tr
                        onClick={() => setExpandedRowId(isExpanded ? null : product.family_id)}
                        className={`hover:bg-slate-50/70 transition-colors cursor-pointer ${
                          isExpanded ? "bg-sky-50/30" : isSelected ? "bg-sky-50/20" : ""
                        }`}
                      >
                        {/* Checkbox */}
                        <td className="py-3.5 px-3">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onClick={(e) => toggleSelectRow(product.family_id, e)}
                            onChange={() => {}}
                            className="w-4 h-4 text-sky-500 rounded focus:ring-sky-500 cursor-pointer"
                          />
                        </td>

                        {/* Row # */}
                        <td className="py-3.5 px-2 text-center text-slate-400 font-mono text-[11px]">
                          {rowNumber}
                        </td>

                        {/* Image */}
                        <td className="py-3.5 px-3">
                          <div className="w-12 h-12 rounded-lg bg-slate-50 border border-slate-100 p-0.5 overflow-hidden flex items-center justify-center">
                            <img
                              src={product.image_url || "/vantis_logo.png"}
                              alt={product.title}
                              className="w-full h-full object-contain mix-blend-multiply"
                            />
                          </div>
                        </td>

                        {/* Product Name */}
                        <td className="py-3.5 px-4 font-bold text-slate-900 max-w-xs">
                          <div className="line-clamp-1">{product.title}</div>
                        </td>

                        {/* Style / SKU */}
                        <td className="py-3.5 px-4 font-mono font-medium text-slate-700 whitespace-nowrap">
                          {product.style || product.sku || "—"}
                        </td>

                        {/* EAN */}
                        <td className="py-3.5 px-4 font-mono text-slate-500 whitespace-nowrap">
                          {product.ean || "—"}
                        </td>

                        {/* Category */}
                        <td className="py-3.5 px-3 font-semibold text-slate-700 whitespace-nowrap">
                          {product.category}
                        </td>

                        {/* Gender */}
                        <td className="py-3.5 px-3 font-semibold text-slate-600 whitespace-nowrap">
                          {product.gender}
                        </td>

                        {/* Sizes */}
                        <td className="py-3.5 px-3 text-center font-bold text-slate-800">
                          {product.sizes_count}
                        </td>

                        {/* Platforms */}
                        <td className="py-3.5 px-3 text-center font-bold text-sky-600">
                          {product.platforms_count}
                        </td>

                        {/* Price & MRP */}
                        <td className="py-3.5 px-4 whitespace-nowrap">
                          <div className="font-extrabold text-sm text-slate-900">
                            {product.lowest_price ? `₹${product.lowest_price.toLocaleString("en-IN")}` : (product.mrp ? `₹${product.mrp.toLocaleString("en-IN")}` : "—")}
                          </div>
                          {product.mrp && product.lowest_price && product.mrp > product.lowest_price ? (
                            <div className="text-[11px] font-mono text-slate-400 line-through">
                              ₹{product.mrp.toLocaleString("en-IN")}
                            </div>
                          ) : (
                            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                              Price
                            </div>
                          )}
                        </td>

                        {/* Action Expand */}
                        <td className="py-3.5 px-3 text-right">
                          <button
                            onClick={(e) => toggleExpand(product.family_id, e)}
                            className="p-1 text-slate-400 hover:text-sky-600 transition-colors"
                          >
                            {isExpanded ? (
                              <ChevronUp className="w-4 h-4" />
                            ) : (
                              <ChevronRight className="w-4 h-4" />
                            )}
                          </button>
                        </td>
                      </tr>

                      {/* Expandable Row with 7 Platform Cards (Matching Image 4) */}
                      {isExpanded && (
                        <tr className="bg-sky-50/20">
                          <td colSpan={13} className="p-4 sm:p-6 border-y border-sky-100">
                            <div className="bg-white rounded-2xl p-6 border border-slate-200/90 shadow-sm space-y-6">
                              {/* Top Product Detail Inside Row */}
                              <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
                                <div className="flex items-center gap-5">
                                  <div className="w-24 h-24 rounded-xl bg-slate-50 border border-slate-100 p-1 shrink-0 overflow-hidden">
                                    <img
                                      src={product.image_url || "/vantis_logo.png"}
                                      alt={product.title}
                                      className="w-full h-full object-contain mix-blend-multiply"
                                    />
                                  </div>
                                  <div className="space-y-1.5">
                                    <h4 className="font-extrabold text-base text-slate-900">
                                      {product.title}
                                    </h4>
                                    <div className="text-xs text-slate-500 font-mono">
                                      Style: <span className="font-bold text-slate-800">{product.style || product.sku || "—"}</span>
                                      {product.ean && ` • EAN: ${product.ean}`}
                                    </div>
                                    <div className="flex flex-wrap gap-1.5 pt-1">
                                      {product.tags.map((t, tidx) => (
                                        <span
                                          key={tidx}
                                          className="bg-sky-50 text-sky-700 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                                        >
                                          {t}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                </div>

                                {/* Circular Stat Chips & View Details CTA */}
                                <div className="flex items-center gap-4">
                                  <div className="flex items-center gap-2">
                                    <div className="w-14 h-14 rounded-full bg-[#EAF6FE] flex flex-col items-center justify-center text-center">
                                      <span className="text-base font-extrabold text-[#079FE0] leading-none">
                                        {product.sizes_count}
                                      </span>
                                      <span className="text-[10px] text-slate-500 font-medium leading-none mt-0.5">
                                        Sizes
                                      </span>
                                    </div>
                                    <div className="w-14 h-14 rounded-full bg-[#EAF6FE] flex flex-col items-center justify-center text-center">
                                      <span className="text-base font-extrabold text-[#079FE0] leading-none">
                                        {product.platforms_count}
                                      </span>
                                      <span className="text-[10px] text-slate-500 font-medium leading-none mt-0.5">
                                        Platforms
                                      </span>
                                    </div>
                                  </div>

                                  <div className="text-right pl-4 border-l border-slate-100">
                                    <div className="text-xl font-black text-slate-900">
                                      {product.lowest_price ? `₹${product.lowest_price.toLocaleString("en-IN")}` : (product.mrp ? `₹${product.mrp.toLocaleString("en-IN")}` : "—")}
                                    </div>
                                    {product.mrp && product.lowest_price && product.mrp > product.lowest_price ? (
                                      <div className="text-xs font-mono text-slate-400 line-through">
                                        MRP ₹{product.mrp.toLocaleString("en-IN")}
                                      </div>
                                    ) : (
                                      <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">
                                        Selling Price
                                      </div>
                                    )}
                                    <button
                                      onClick={() => navigate(`/products/${encodeURIComponent(product.family_id)}`)}
                                      className="mt-2 inline-flex items-center gap-1.5 px-4 py-2 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs font-bold rounded-xl transition-all shadow-xs cursor-pointer"
                                    >
                                      <span>View Details</span>
                                      <ArrowRight className="w-3.5 h-3.5" />
                                    </button>
                                  </div>
                                </div>
                              </div>

                              {/* Platform Availability Grid (Cards for 7 Platforms) */}
                              <div className="space-y-2 pt-2 border-t border-slate-100">
                                <div className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                                  Platform Availability
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-7 gap-3">
                                  {product.platforms.map((plat) => {
                                    const hasPlat = plat.price !== null && plat.price !== undefined && plat.price > 0;
                                    return (
                                      <div
                                        key={plat.platform}
                                        className="p-3 bg-slate-50/70 rounded-xl border border-slate-200/80 space-y-1.5"
                                      >
                                        <div className="font-bold text-xs text-slate-800 truncate">
                                          {plat.platform_name}
                                        </div>
                                        <div className="flex items-baseline gap-1.5 flex-wrap">
                                          <span className="font-extrabold text-sm text-slate-900">
                                            {hasPlat && plat.price ? `₹${plat.price.toLocaleString("en-IN")}` : "—"}
                                          </span>
                                          {hasPlat && plat.mrp && plat.mrp > (plat.price || 0) && (
                                            <span className="text-[10px] font-mono text-slate-400 line-through">
                                              ₹{plat.mrp.toLocaleString("en-IN")}
                                            </span>
                                          )}
                                        </div>
                                        <div className="flex items-center gap-1 text-[10px] font-semibold">
                                          <span
                                            className={`w-1.5 h-1.5 rounded-full ${
                                              hasPlat
                                                ? plat.availability_status === "In stock"
                                                  ? "bg-emerald-500"
                                                  : plat.availability_status === "Limited stock"
                                                  ? "bg-amber-500"
                                                  : "bg-rose-500"
                                                : "bg-slate-300"
                                            }`}
                                          />
                                          <span className={hasPlat ? "text-slate-700" : "text-slate-400"}>
                                            {hasPlat ? plat.availability_status : "No data available"}
                                          </span>
                                        </div>
                                        <div className="text-[10px] text-slate-400">
                                          {hasPlat ? plat.sizes_summary : "—"}
                                        </div>
                                        {hasPlat && plat.offers && plat.offers.length > 0 && (
                                          <div className="mt-1 pt-1 border-t border-slate-200/60 flex items-center gap-1 text-[10px] font-bold text-amber-800 bg-amber-50/90 px-1.5 py-0.5 rounded border border-amber-200/80 truncate shadow-2xs">
                                            <Tag className="w-2.5 h-2.5 text-amber-600 shrink-0" />
                                            <span className="truncate" title={(plat.offers[0].title || plat.offers[0].description || plat.offers[0].code) ?? undefined}>
                                              {plat.offers[0].code ? `Code: ${plat.offers[0].code}` : (plat.offers[0].title || `${plat.offers.length} Offers`)}
                                            </span>
                                          </div>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Footer */}
        <div className="p-4 bg-slate-50/70 border-t border-slate-200 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs font-semibold text-slate-600">
          {/* Page size selector */}
          <div className="flex items-center gap-2">
            <span>Show</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="py-1 px-2.5 bg-white border border-slate-200 rounded-lg text-xs font-bold text-slate-800 cursor-pointer"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
            </select>
            <span>products per page</span>
          </div>

          {/* Page Numbers */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 transition-colors cursor-pointer"
            >
              &lt;
            </button>

            {(() => {
              const maxButtons = 5;
              let start = Math.max(1, page - 2);
              let end = Math.min(totalPages, start + maxButtons - 1);
              if (end - start < maxButtons - 1) {
                start = Math.max(1, end - maxButtons + 1);
              }
              const pages: number[] = [];
              for (let i = start; i <= end; i++) {
                pages.push(i);
              }

              return (
                <>
                  {start > 1 && (
                    <>
                      <button
                        onClick={() => setPage(1)}
                        className="w-7 h-7 rounded-lg bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold transition-colors cursor-pointer"
                      >
                        1
                      </button>
                      {start > 2 && <span className="px-1 text-slate-400">...</span>}
                    </>
                  )}

                  {pages.map((pNum) => (
                    <button
                      key={pNum}
                      onClick={() => setPage(pNum)}
                      className={`w-7 h-7 rounded-lg transition-colors font-bold cursor-pointer ${
                        page === pNum
                          ? "bg-[#079FE0] text-white shadow-2xs"
                          : "bg-white border border-slate-200 hover:bg-slate-100 text-slate-700"
                      }`}
                    >
                      {pNum}
                    </button>
                  ))}

                  {end < totalPages && (
                    <>
                      {end < totalPages - 1 && <span className="px-1 text-slate-400">...</span>}
                      <button
                        onClick={() => setPage(totalPages)}
                        className="w-7 h-7 rounded-lg bg-white border border-slate-200 hover:bg-slate-100 text-slate-700 font-bold transition-colors cursor-pointer"
                      >
                        {totalPages}
                      </button>
                    </>
                  )}
                </>
              );
            })()}

            <button
              onClick={() => setPage(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages}
              className="px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:bg-slate-100 disabled:opacity-40 transition-colors cursor-pointer"
            >
              &gt;
            </button>

            {/* Custom Page Jump Input */}
            <div className="flex items-center gap-1.5 pl-2 ml-1 border-l border-slate-200">
              <span className="text-slate-500 font-medium">Page</span>
              <input
                type="number"
                min={1}
                max={totalPages}
                value={jumpPage}
                onChange={(e) => setJumpPage(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    const p = parseInt(jumpPage, 10);
                    if (!isNaN(p) && p >= 1 && p <= totalPages) {
                      setPage(p);
                      setJumpPage("");
                    }
                  }
                }}
                className="w-14 px-2 py-1 bg-white border border-slate-200 rounded-lg text-center font-bold text-slate-800 text-xs focus:outline-none focus:ring-1 focus:ring-sky-500"
                placeholder={String(page)}
              />
              <span className="text-slate-400 font-normal">/ {totalPages}</span>
              <button
                type="button"
                onClick={() => {
                  const p = parseInt(jumpPage, 10);
                  if (!isNaN(p) && p >= 1 && p <= totalPages) {
                    setPage(p);
                    setJumpPage("");
                  }
                }}
                className="px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-white font-bold rounded-lg text-xs cursor-pointer transition-colors shadow-2xs"
              >
                Go
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CataloguePage;
