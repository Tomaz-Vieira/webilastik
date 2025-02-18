import { mat4, quat, vec3 } from "gl-matrix";


/**
 * A data source from a viewer. Usually
 */
export interface INativeView{
    name: string,
    url: string,
}

/**
 * Represents glue code with Basic functionality that any viewer must implement to be able to be used by
 * the ilastik overlay.
 */
export interface IViewerDriver{
    /**
     * @returns an array of all viewport drivers corresponding to the currently visible
     * viewports of the viewer. See IViewportDriver for more details
     */
    getViewportDrivers: () => Array<IViewportDriver>;
    /**
     * @returns the HTML element that is actually displaying the data pixels in the viewer.
     * This element is "tracked" by the ilastik overlay, i.e., the overlay stays on floating
     * on top of the tracked element and forces itself to have the same size as the tracked element
     */
    getTrackedElement: () => HTMLElement;

    /**
     * Opens data at params.native_view.url (preferably in a 'tab' named params.native_view.name) or refreshes that tab
     * if the url is already open.
     * @param params.url - the url to open or refresh
     * @param params.name - a hint of the name to be used for this data
     * @param params.channel_colors - a hint on how to interpret the channels of the data incoming from params.url
     * This is particulary useful for pixel prediction urls, since each channel has the color of a brush stroke
     */
    refreshView: (params: {native_view: INativeView, similar_url_hint?: string, channel_colors?: vec3[]}) => void;

    /**
     * Registers a calback that should be called every time the viewer:
     *  -> opens or closes a data source;
     *  -> displays or hides a data source;
     *  -> reconfigures the visible viewports
     *
     * The callback should be called essentially every time the folloing methods would change their results:
     *      this.getViewportDrivers
     *      this.getDataViewOnDisplay
     *      this.getOpenDataViews
     *
     * Note that the handler is _not_ to be called every time the user scrolls, pans or rotates the view
     *
     * @param handler - a callback thta is to be called every time the visible viewports change
     */
    onViewportsChanged: (handler: () => void) => void;

    /**
     * Gets the IDataView being displayed, if any. This is usually somethingl like the "active tab" of a viewer
     *
     * @returns The IDataView representing the data source currently being actively viewed, if any
     */
    getDataViewOnDisplay(): INativeView | undefined;

    /**
     * @returns an array of `IDataView`s representing all data sources currently opened by the viewer
     */
    getOpenDataViews(): Array<INativeView>;
}

/**
 * A description of a viewport's offset and geometry relative to the entirety of the display area; analogous to a WebGl viewport
 */
export interface IViewportGeometry{
    left: number;
    bottom: number;
    width: number;
    height: number;
}

/**
 * Hints on how to inject the overlay div that captures mouse events into the DOM
 */
export interface IViewportInjectionParams{
    precedingElement?: HTMLElement;
    zIndex?: string
}

/**
 * A viewer can be broken down into multiple viewports, that is, multiple non-overlapping
 * mini-screens within the main view where it can show the same data, but from different angles or
 * with different viewing options. An IViewerDriver should provide as many of these viewport drivers
 * as there are "brushable" viewports in the viewer.
 *
 * The reason to have multiple IVewportDriver instead of simply having multiple IViewerDrivers
 * is that by splitting a single canvas into multiple viewports it is possible to have a single webgl
 * context be shared between them.
 */
export interface IViewportDriver{
    getGeometry(): IViewportGeometry;

    /**
     * @returns the camera position and orientation in data space
     */
    getCameraPoseInUvwSpace(): {position_uvw: vec3, orientation_uvw: quat};

    /**
     * @returns a mat4 that converts from voxel to worlkd space. Scaling part must have at least one axis set to 1
     */
    getUvwToWorldMatrix(): mat4;

    /**
     * @returns orthogonal zoom; must be positive. Describes how many pixels (the smallest dimension of) one voxel should occupy on screen
     */
    getZoomInPixelsPerNm(): number;

    /**
     * Moves the viewport camera over to pose
     *
     * @param pose.voxel_position_uvw - position to snap to, in data space
     * @param pose.voxel_orientation_uvw - orientation to snap to, in data space
     */
    snapCameraTo?: (pose: {voxel_position_uvw: vec3, orientation_uvw: quat}) => any;
    getInjectionParams?: () => IViewportInjectionParams
}
