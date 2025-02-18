import { vec3, mat4, quat } from "gl-matrix"
import { IViewportDriver, IViewerDriver } from "..";
import { getElementContentRect, uuidv4} from "../util/misc";
import { Url } from "../util/parsed_url";
import { INativeView } from "./viewer_driver";

type NeuroglancerLayout = "4panel" | "xy" | "xy-3d" | "xz" | "xz-3d" | "yz" | "yz-3d";

export class NeuroglancerViewportDriver implements IViewportDriver{
    private viewer: any
    constructor(
        public readonly viewer_driver: NeuroglancerDriver,
        public readonly panel: HTMLElement,
        private readonly orientation_offset: quat,
    ){
        this.viewer = viewer_driver.viewer
    }
    public getCameraPoseInUvwSpace = () => {
        const orientation_uvw = quat.multiply(
            quat.create(), this.viewer.navigationState.pose.orientation.orientation, this.orientation_offset
        )
        const ng_position_obj = this.viewer.navigationState.pose.position
        //old neuroglancers do not have the "value" key
        //FIXME: check if this is in Nm and not finest-voxel-space
        const position_uvw = "value" in ng_position_obj ? ng_position_obj.value : ng_position_obj.spatialCoordinates
        return {
            position_uvw: position_uvw as vec3,
            orientation_uvw: quat.normalize(orientation_uvw, orientation_uvw),
        }
    }
    public getUvwToWorldMatrix(): mat4{
        return mat4.fromScaling(mat4.create(), vec3.fromValues(1, -1, -1))
    }
    public getZoomInPixelsPerNm(): number{
        //FIXME: check if this is acually in Nm and not in finest-voxel-units
        return 1 / this.viewer.navigationState.zoomFactor.value
    }
    public getGeometry = () => {
        const panelContentRect = getElementContentRect(this.panel)
        const trackedElementRect = getElementContentRect(this.viewer_driver.getTrackedElement())
        return {
            left: panelContentRect.left - trackedElementRect.left,
            bottom: panelContentRect.bottom - trackedElementRect.bottom,
            width: panelContentRect.width,
            height: panelContentRect.height,
        }
    }
    public getInjectionParams = () => ({
        precedingElement: this.panel,
        // zIndex: 10
    })
}

interface INeuroglancerLayer{
    name: string,
    source: string,
    visible: boolean,
    shader: string | undefined
    type?: string
}

export class NeuroglancerDriver implements IViewerDriver{
    constructor(public readonly viewer: any){}
    getTrackedElement() : HTMLElement{
        return document.querySelector("canvas")! //FIXME: double-check selector
    }
    getViewportDrivers(): Array<IViewportDriver>{
        const panels = Array(...document.querySelectorAll(".neuroglancer-panel")) as Array<HTMLElement>;
        if(panels.length == 0){
            return []
        }
        const layout: NeuroglancerLayout = this.viewer.state.toJSON()["layout"]
        const orientation_offsets = new Map<string, quat>([
            ["xy", quat.create()],
            ["xz", quat.setAxisAngle(quat.create(), vec3.fromValues(1, 0, 0), Math.PI / 2)], // FIXME
            ["yz", quat.setAxisAngle(quat.create(), vec3.fromValues(0, 1, 0), Math.PI / 2)],//FIXME
        ])
        if(layout == "4panel"){
            console.log("Detected 4panel layout!s!")
            return [
                new NeuroglancerViewportDriver(this, panels[0], orientation_offsets.get("xy")!),
                new NeuroglancerViewportDriver(this, panels[1], orientation_offsets.get("xz")!),
                new NeuroglancerViewportDriver(this, panels[3], orientation_offsets.get("yz")!),
            ]
        }
        return [new NeuroglancerViewportDriver(this, panels[0], orientation_offsets.get(layout.replace("-3d", ""))!)]
    }
    onViewportsChanged(handler: () => void){
        this.viewer.layerManager.layersChanged.add(() => {
            if(this.viewer.state.toJSON().layers.find((layer: INeuroglancerLayer) => layer.type === undefined)){
                return // if any layer has no type, then the viwer hasn't settled yet
            }
            handler()
        })
        // this.viewer.layerManager.layersChanged.add(() => handler())
        // this.viewer.layout.changed.add(() => handler())
    }
    refreshView(params: {native_view: INativeView, similar_url_hint?: string, channel_colors?: vec3[]}){
        let shader: string | undefined = undefined;
        if(params.channel_colors !== undefined){
            shader = this.makePredictionsShader(params.channel_colors)
        }else if(params.similar_url_hint !== undefined){
            const similar_layers = this.getImageLayers().filter(layer => layer.source == params.similar_url_hint)
            if(similar_layers.length > 0){
                shader = similar_layers[0].shader
            }
        }
        this.refreshLayer({name: params.native_view.name, url: params.native_view.url, shader})
    }

    private refreshLayer({name, url, shader}: {name: string, url: string, shader?: string}){
        this.dropLayer(name)
        const cache_busting_url = Url.parse(url)
            // .updatedWith({ //FIXME: this needs patching NG to handle query params
            //     extra_search: new Map<string, string>([["cache_busting_random", uuidv4()]])
            // })
            .double_protocol_raw
            .replace(/run_id=[^/?]+/, `run_id=${uuidv4()}`) // FIXME
        console.log(`Refreshing layer '${name}' with url ${cache_busting_url}`)
        this.openNewDataSource({name, url: cache_busting_url, shader})
    }

    private getLayerManager(): any {
        return this.viewer.layerSpecification.layerManager;
    }

    private dropLayer(name: string): boolean{
        const layerManager = this.getLayerManager();
        const predictionsLayer = layerManager.getLayerByName(name);

        if(predictionsLayer !== undefined){
            layerManager.removeManagedLayer(predictionsLayer);
            return true
        }
        return false
    }

    private openNewDataSource(params: {name: string, url: string, shader?: string}){
        const newPredictionsLayer = this.viewer.layerSpecification.getLayer(
            params.name,
            {source: params.url, shader: params.shader}
        );
        this.viewer.layerSpecification.add(newPredictionsLayer);
    }

    private makePredictionsShader(channel_colors: Array<vec3>): string{
            let color_lines = channel_colors.map((c: vec3, idx: number) => {
                return `vec3 color${idx} = (vec3(${c[0]}, ${c[1]}, ${c[2]}) / 255.0) * toNormalized(getDataValue(${idx}));`
            })
            let colors_to_mix = channel_colors.map((_: vec3, idx: number) => `color${idx}`)

            return [
                "void main() {",
                "    " + color_lines.join("\n    "),
                "    emitRGBA(",
                `        vec4(${colors_to_mix.join(' + ')}, 1.0)`,
                "    );",
                "}",
            ].join("\n")
    }

    public getImageLayers() : Array<INeuroglancerLayer>{
        return (this.viewer.state.toJSON().layers || [])
        .filter((l: any) => l.type == "image")
        .map((l: any) : INeuroglancerLayer => ({
                name: l.name,
                source: l.source.replace(/\bgs:\/\//, "https://storage.googleapis.com/"),
                visible: l.visible  === undefined ? true : l.visible,
                shader: l.shader
        }));
    }

    public getOpenDataViews(): Array<INativeView>{
        return this.getImageLayers().map(layer => ({name: layer.name, url: layer.source}))
    }

    public getDataViewOnDisplay(): INativeView | undefined{
        return this.getImageLayers()
            .filter(layer => layer.visible)
            .map(layer => ({
                name: layer.name,
                url: layer.source,
            }))[0];
    }
}
