import React, { useEffect, useRef } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';

// Remove Cesium Ion dependency completely - strictly token-free
Cesium.Ion.defaultAccessToken = '';

interface Cesium3DViewProps {
  tilesetUrl: string;
  selectedLevel: string;
  selectedVolumeId: string | null;
  wireframe: boolean;
  onSelectVolume: (volumeId: string) => void;
}

export const Cesium3DView: React.FC<Cesium3DViewProps> = ({
  tilesetUrl,
  selectedLevel,
  selectedVolumeId: _selectedVolumeId,
  wireframe,
  onSelectVolume,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const tilesetRef = useRef<Cesium.Cesium3DTileset | null>(null);
  const selectedLevelRef = useRef<string>(selectedLevel);

  // Helper to apply level visibility hiding across all loaded and child tiles
  const applyLevelVisibility = (tileset: any, targetLevel: string) => {
    if (!tileset) return;
    const hideOrShowTile = (tile: any) => {
      if (!tile) return;
      if (tile.content) {
        const uri = String(tile.content.uri || tile.content._resource?.url || '');
        const isMatch = (targetLevel === 'ALL') || uri.includes(`${targetLevel}.glb`);
        tile.content.show = isMatch;
        if (tile.content._model) {
          tile.content._model.show = isMatch;
        }
      }
      if (tile.children && Array.isArray(tile.children)) {
        tile.children.forEach(hideOrShowTile);
      }
    };
    if (tileset.root) {
      hideOrShowTile(tileset.root);
    }
  };

  // Immediate level isolation when selectedLevel changes
  useEffect(() => {
    selectedLevelRef.current = selectedLevel;
    if (tilesetRef.current) {
      applyLevelVisibility(tilesetRef.current, selectedLevel);
    }
    if (viewerRef.current) {
      viewerRef.current.scene.requestRender();
    }
  }, [selectedLevel]);

  // Building center in Kurla, Mumbai: EPSG:32643 (278504.0, 2110503.0) -> WGS84
  const BUILDING_LON = 72.894947;
  const BUILDING_LAT = 19.075422;

  // Parcel boundary: converted from EPSG:32643 UTM 43N to WGS84 EPSG:4326 using pyproj
  // Original coords in building_spec.json:
  //   [278480.0, 2110485.0], [278530.0, 2110485.0], [278530.0, 2110525.0], [278480.0, 2110525.0]
  // Transformed WGS84 degrees (Lon, Lat):
  const PARCEL_BOUNDARY_WGS84 = [
    72.8947215, 19.0752573,
    72.8951964, 19.0752627,
    72.8951919, 19.0756240,
    72.8947169, 19.0756185,
    72.8947215, 19.0752573,
  ];

  useEffect(() => {
    if (!containerRef.current) return;

    // Token-free imagery provider: OpenStreetMap via UrlTemplateImageryProvider
    const tokenFreeBaseLayer = new Cesium.ImageryLayer(
      new Cesium.UrlTemplateImageryProvider({
        url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        subdomains: ['a', 'b', 'c'],
        maximumLevel: 19,
      })
    );

    // Initialize Cesium Viewer with token-free base layer and flat ellipsoid terrain
    const viewer = new Cesium.Viewer(containerRef.current, {
      animation: false,
      timeline: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,
      baseLayerPicker: false,
      navigationHelpButton: false,
      infoBox: false,
      selectionIndicator: false,
      shadows: false,
      shouldAnimate: false,
      baseLayer: tokenFreeBaseLayer,
      terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    });

    viewerRef.current = viewer;

    // Suppress default Cesium credit banner / ion access token notice
    if (viewer.cesiumWidget && viewer.cesiumWidget.creditContainer) {
      (viewer.cesiumWidget.creditContainer as HTMLElement).style.display = 'none';
    }

    // Disable depth testing against terrain so subsurface basement (B01: -3.20m to 0m) is visible
    viewer.scene.globe.depthTestAgainstTerrain = false;

    // Add 2D Cadastral Parcel boundary polygon (converted to WGS84)
    viewer.entities.add({
      name: 'Parent Parcel 12345678901234',
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(PARCEL_BOUNDARY_WGS84),
        material: Cesium.Color.fromCssColorString('#facc15').withAlpha(0.18),
        outline: true,
        outlineColor: Cesium.Color.fromCssColorString('#eab308'),
        outlineWidth: 3,
        height: 0,
      },
    });

    // Camera view of the 3D building stack
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(BUILDING_LON, BUILDING_LAT - 0.0009, 85.0),
      orientation: {
        heading: Cesium.Math.toRadians(0.0),
        pitch: Cesium.Math.toRadians(-35.0),
        roll: 0.0,
      },
      duration: 1.0,
    });

    // Load API-served OGC 3D Tileset (one tile per level)
    Cesium.Cesium3DTileset.fromUrl(tilesetUrl)
      .then((tileset) => {
        tilesetRef.current = tileset;
        viewer.scene.primitives.add(tileset);
        tileset.debugWireframe = wireframe;

        // Apply initial level visibility filter
        applyLevelVisibility(tileset, selectedLevelRef.current);

        // Keep level visibility filter synchronized as new tiles stream in
        tileset.tileVisible.addEventListener((tile: any) => {
          const currentLevel = selectedLevelRef.current;
          if (tile && tile.content) {
            const uri = String(tile.content.uri || tile.content._resource?.url || '');
            const isMatch = (currentLevel === 'ALL') || uri.includes(`${currentLevel}.glb`);
            tile.content.show = isMatch;
            if (tile.content._model) {
              tile.content._model.show = isMatch;
            }
          }
        });

        viewer.scene.requestRender();
      })
      .catch((err) => {
        console.warn('Tileset proxy load note:', err);
      });

    // Screen-space click picking handler
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((movement: { position: Cesium.Cartesian2 }) => {
      const picked = viewer.scene.pick(movement.position);
      if (Cesium.defined(picked)) {
        let volId: string | null = null;
        if (typeof (picked as any).getProperty === 'function') {
          volId = (picked as any).getProperty('volume_id');
        }
        if (!volId && (picked as any).node && typeof (picked as any).node.name === 'string') {
          const match = (picked as any).node.name.match(/Volume_(\d+)/);
          if (match) volId = match[1];
        }
        if (!volId && typeof (picked as any).id === 'string') {
          const match = (picked as any).id.match(/Volume_(\d+)/);
          if (match) volId = match[1];
        }
        if (!volId && (picked as any).content && (picked as any).content.uri) {
          const uri = String((picked as any).content.uri);
          const lvlMap: Record<string, string> = {
            'B01': '001',
            'G00': '002',
            'F01': '004',
            'F02': '006',
            'F03': '008',
          };
          for (const [lvl, id] of Object.entries(lvlMap)) {
            if (uri.includes(`${lvl}.glb`)) {
              volId = id;
              break;
            }
          }
        }
        if (volId) {
          onSelectVolume(String(volId));
        }
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      handler.destroy();
      viewer.destroy();
      viewerRef.current = null;
      tilesetRef.current = null;
    };
  }, [tilesetUrl]);

  // Wireframe updates
  useEffect(() => {
    if (tilesetRef.current) {
      tilesetRef.current.debugWireframe = wireframe;
      if (viewerRef.current) {
        viewerRef.current.scene.requestRender();
      }
    }
  }, [wireframe]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%', position: 'relative' }} />;
};


