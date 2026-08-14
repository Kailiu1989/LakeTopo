//尾迹线 流动
class PolylineWakeLineMaterialProperty {
    constructor(options) {
        options = Cesium.defaultValue(options, Cesium.defaultValue.EMPTY_OBJECT);
        this._definitionChanged = new Cesium.Event();
        this._color = undefined;
        this._colorSubscription = undefined;
        this.color = options.color;
        this.duration = options.duration;
        this._time = performance.now();
    }
}
Object.defineProperties(PolylineWakeLineMaterialProperty.prototype, {
    isConstant: {
        get: function() {
            return false;
        }
    },
    definitionChanged: {
        get: function() {
            return this._definitionChanged;
        }
    },
    color: Cesium.createPropertyDescriptor('color')
});

PolylineWakeLineMaterialProperty.prototype.getType = function(time) {
    return 'PolylineTrialFlow';
}

PolylineWakeLineMaterialProperty.prototype.getValue = function(time, result) {
    if (!Cesium.defined(result)) {
        result = {};
    }
    result.color = Cesium.Property.getValueOrClonedDefault(this._color, time, Cesium.Color.WHITE, result.color);
    result.time = ((performance.now() - this._time) % this.duration) / this.duration;
    return result;
}

PolylineWakeLineMaterialProperty.prototype.equals = function(other) {
    return this === other ||
        (other instanceof PolylineWakeLineMaterialProperty &&
            this.duration == other.duration &&
            Cesium.Property.equals(this._color, other._color))
}
Cesium.PolylineWakeLineMaterialProperty = PolylineWakeLineMaterialProperty;
Cesium.Material.PolylineTrialFlowType = 'PolylineTrialFlow';
Cesium.Material.PolylineTrialFlowSource = 'czm_material czm_getMaterial(czm_materialInput materialInput)\n' +
    '{\n' +
    '    czm_material material = czm_getDefaultMaterial(materialInput);\n' +
    '    vec2 st = materialInput.st;\n' +
    '    float t = time;\n' +
    '    t *= 1.2;\n' +
    '    float alpha = smoothstep(t- 0.4, t, st.s) * step(-t, -st.s);\n' + // t- 0.4 为尾迹线长度越大越长
    '    alpha += 0.05;\n' + // 线最底层透明度 越小底线越透明
    '    material.diffuse= color.rgb;\n' +
    '    material.alpha = alpha;\n' +
    '    return material;\n' +
    '}\n'

Cesium.Material._materialCache.addMaterial(Cesium.Material.PolylineTrialFlowType, {
    fabric: {
        type: Cesium.Material.PolylineTrialFlowType,
        uniforms: {
            color: new Cesium.Color(1.0, 0.0, 0.0, 0.5),
            transparent: true,
            time: 20
        },
        source: Cesium.Material.PolylineTrialFlowSource
    },
    translucent: function(material) {
        return true;
    }
});

