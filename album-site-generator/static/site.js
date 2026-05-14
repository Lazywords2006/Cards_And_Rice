(function () {
  function normalizedText(value) {
    return String(value || "").toLowerCase();
  }

  function setVisible(el, visible) {
    el.style.display = visible ? "" : "none";
  }

  function initLazyLoad() {
    if (!("IntersectionObserver" in window)) {
      return;
    }

    var images = document.querySelectorAll('img[loading="lazy"]');
    if (!images.length) {
      return;
    }

    var io = new IntersectionObserver(function (entries, observer) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) {
          return;
        }
        var target = entry.target;
        if (target.dataset.src) {
          target.src = target.dataset.src;
        }
        observer.unobserve(target);
      });
    });

    images.forEach(function (img) {
      io.observe(img);
    });
  }

  function initSidePanel() {
    var panel = document.getElementById("groupPanel");
    if (!panel) {
      return;
    }

    var toggleButtons = document.querySelectorAll("[data-panel-toggle]");
    var closeButtons = document.querySelectorAll("[data-panel-close]");
    var mobileQuery = window.matchMedia("(max-width: 720px)");

    function isMobile() {
      return mobileQuery.matches;
    }

    function syncPanelMode() {
      if (isMobile()) {
        panel.setAttribute("aria-hidden", panel.classList.contains("open") ? "false" : "true");
        return;
      }

      panel.classList.add("open");
      panel.setAttribute("aria-hidden", "false");
      document.body.classList.remove("has-side-panel-open");
      toggleButtons.forEach(function (btn) {
        btn.setAttribute("aria-expanded", "true");
      });
    }

    function setOpen(open) {
      if (!isMobile()) {
        syncPanelMode();
        return;
      }

      panel.classList.toggle("open", open);
      panel.setAttribute("aria-hidden", open ? "false" : "true");
      document.body.classList.toggle("has-side-panel-open", open);
      toggleButtons.forEach(function (btn) {
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }

    toggleButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setOpen(!panel.classList.contains("open"));
      });
    });

    closeButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setOpen(false);
      });
    });

    panel.querySelectorAll("[data-group-link]").forEach(function (link) {
      link.addEventListener("click", function () {
        if (isMobile()) {
          setOpen(false);
        }
      });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    });

    if (typeof mobileQuery.addEventListener === "function") {
      mobileQuery.addEventListener("change", syncPanelMode);
    } else if (typeof mobileQuery.addListener === "function") {
      mobileQuery.addListener(syncPanelMode);
    }

    syncPanelMode();
  }

  function initAlbumSearch() {
    var input = document.getElementById("albumSearchInput");
    if (!input) {
      return;
    }

    var result = document.getElementById("albumSearchResult");
    var groups = Array.prototype.slice.call(document.querySelectorAll(".desc-group"));
    var groupLinks = Array.prototype.slice.call(document.querySelectorAll("[data-group-link]"));

    function applySearch() {
      var query = normalizedText(input.value.trim());
      var visibleGroupCount = 0;
      var visiblePhotoCount = 0;

      groups.forEach(function (group) {
        var groupText = normalizedText(group.getAttribute("data-search"));
        var cards = Array.prototype.slice.call(group.querySelectorAll(".photo-card"));
        var groupMatch = query.length === 0 || groupText.indexOf(query) !== -1;
        var hasVisibleCard = false;

        cards.forEach(function (card) {
          var cardText = normalizedText(card.getAttribute("data-search") || card.textContent);
          var cardMatch = query.length === 0 || groupMatch || cardText.indexOf(query) !== -1;
          setVisible(card, cardMatch);
          if (cardMatch) {
            hasVisibleCard = true;
            visiblePhotoCount += 1;
          }
        });

        setVisible(group, hasVisibleCard);
        if (hasVisibleCard) {
          visibleGroupCount += 1;
        }
      });

      groupLinks.forEach(function (link) {
        var targetId = (link.getAttribute("href") || "").replace("#", "");
        var target = targetId ? document.getElementById(targetId) : null;
        var visible = !target || target.style.display !== "none";
        setVisible(link, visible);
      });

      if (result) {
        result.textContent = query
          ? "匹配板块 " + visibleGroupCount + "，图片 " + visiblePhotoCount
          : "";
      }
    }

    input.addEventListener("input", applySearch);
    applySearch();
  }

  function initSiteSearch() {
    var input = document.getElementById("siteSearchInput");
    if (!input) {
      return;
    }

    var result = document.getElementById("siteSearchResult");
    var albums = Array.prototype.slice.call(document.querySelectorAll(".album-card"));
    var timelineItems = Array.prototype.slice.call(document.querySelectorAll(".timeline li"));

    function applySearch() {
      var query = normalizedText(input.value.trim());
      var visibleAlbumCount = 0;
      var visibleTimelineCount = 0;

      albums.forEach(function (item) {
        var text = normalizedText(item.getAttribute("data-search") || item.textContent);
        var visible = query.length === 0 || text.indexOf(query) !== -1;
        setVisible(item, visible);
        if (visible) {
          visibleAlbumCount += 1;
        }
      });

      timelineItems.forEach(function (item) {
        var text = normalizedText(item.getAttribute("data-search") || item.textContent);
        var visible = query.length === 0 || text.indexOf(query) !== -1;
        setVisible(item, visible);
        if (visible) {
          visibleTimelineCount += 1;
        }
      });

      if (result) {
        result.textContent = query
          ? "匹配分类 " + visibleAlbumCount + "，最近更新 " + visibleTimelineCount
          : "";
      }
    }

    input.addEventListener("input", applySearch);
    applySearch();
  }

  function initPhotoCardLayout() {
    var cards = Array.prototype.slice.call(document.querySelectorAll(".photo-card"));
    if (!cards.length) {
      return;
    }

    cards.forEach(function (card) {
      var img = card.querySelector("img");
      if (!img) {
        return;
      }

      function applyClass() {
        if (!img.naturalWidth || !img.naturalHeight) {
          return;
        }
        var ratio = img.naturalWidth / img.naturalHeight;
        card.classList.remove("is-portrait", "is-landscape");
        if (ratio < 0.85) {
          card.classList.add("is-portrait");
        } else if (ratio > 1.35) {
          card.classList.add("is-landscape");
        }
      }

      if (img.complete) {
        applyClass();
      } else {
        img.addEventListener("load", applyClass, { once: true });
      }
    });
  }

  function initLightbox() {
    var overlay = document.getElementById("siteLightbox");
    if (!overlay) {
      return;
    }

    var image = document.getElementById("lightboxImage");
    var caption = document.getElementById("lightboxCaption");
    var closeButton = overlay.querySelector("[data-lightbox-close]");
    var prevButton = overlay.querySelector("[data-lightbox-prev]");
    var nextButton = overlay.querySelector("[data-lightbox-next]");
    var state = {
      images: [],
      index: 0,
    };

    function render() {
      var current = state.images[state.index];
      if (!current) {
        return;
      }

      image.src = current.src;
      image.alt = current.alt || "";
      caption.textContent = (state.index + 1) + " / " + state.images.length + " · " + (current.alt || "");
      prevButton.disabled = state.images.length <= 1;
      nextButton.disabled = state.images.length <= 1;
    }

    function open(images, startIndex) {
      if (!images || !images.length) {
        return;
      }

      state.images = images;
      state.index = Math.max(0, Math.min(startIndex || 0, images.length - 1));
      render();
      overlay.hidden = false;
      overlay.setAttribute("aria-hidden", "false");
      document.body.classList.add("has-lightbox-open");
    }

    function close() {
      overlay.hidden = true;
      overlay.setAttribute("aria-hidden", "true");
      image.removeAttribute("src");
      image.removeAttribute("alt");
      document.body.classList.remove("has-lightbox-open");
    }

    function move(step) {
      if (state.images.length <= 1) {
        return;
      }

      state.index = (state.index + step + state.images.length) % state.images.length;
      render();
    }

    document.querySelectorAll("[data-lightbox-trigger]").forEach(function (trigger) {
      trigger.addEventListener("click", function () {
        var card = trigger.closest("[data-lightbox-images]");
        if (!card) {
          return;
        }

        var images;
        try {
          images = JSON.parse(card.getAttribute("data-lightbox-images") || "[]");
        } catch (error) {
          images = [];
        }

        open(images, parseInt(trigger.getAttribute("data-start-index") || "0", 10));
      });
    });

    closeButton.addEventListener("click", close);
    prevButton.addEventListener("click", function () {
      move(-1);
    });
    nextButton.addEventListener("click", function () {
      move(1);
    });

    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) {
        close();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (overlay.hidden) {
        return;
      }

      if (event.key === "Escape") {
        close();
      } else if (event.key === "ArrowLeft") {
        move(-1);
      } else if (event.key === "ArrowRight") {
        move(1);
      }
    });
  }

  initLazyLoad();
  initSidePanel();
  initAlbumSearch();
  initSiteSearch();
  initPhotoCardLayout();
  initLightbox();
})();
